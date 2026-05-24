from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the repository's repeatable local verification checks."
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Assume dependencies are already installed and skip uv sync.",
    )
    parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Skip Docker Compose configuration validation.",
    )
    parser.add_argument(
        "--with-compose",
        action="store_true",
        help="Require Docker Compose configuration validation.",
    )
    args = parser.parse_args()

    checks: list[tuple[str, Sequence[str], dict[str, str] | None]] = []
    if not args.skip_sync:
        checks.append(("Install dependencies", ("uv", "sync", "--locked", "--all-extras"), None))
    checks.extend(
        [
            (
                "Compile Python sources",
                ("uv", "run", "python", "-m", "compileall", "src", "tests", "migrations"),
                None,
            ),
            ("Lint", ("uv", "run", "ruff", "check", "."), None),
            ("Typecheck", ("uv", "run", "mypy", "src"), None),
            ("Pytest suite", ("uv", "run", "pytest"), None),
            (
                "Unit tests via unittest",
                ("uv", "run", "python", "-m", "unittest", "discover", "-s", "tests/unit"),
                {"PYTHONPATH": "src"},
            ),
        ]
    )

    for label, command, env_overlay in checks:
        if not run(label, command, env_overlay=env_overlay):
            return 1

    if not run_optional("Git diff whitespace check", ("git", "diff", "--check")):
        return 1

    if not args.skip_compose:
        compose_command = (
            "docker",
            "compose",
            "--env-file",
            "connector.env.example",
            "-f",
            "deploy/portainer/docker-compose.yml",
            "config",
            "--quiet",
        )
        if args.with_compose:
            if not run("Docker Compose config", compose_command):
                return 1
        else:
            run_optional("Docker Compose config", compose_command)

    print("\nAll requested verification checks completed.")
    return 0


def run(label: str, command: Sequence[str], *, env_overlay: dict[str, str] | None = None) -> bool:
    print(f"\n==> {label}")
    print(format_command(command))
    env = os.environ.copy()
    if env_overlay:
        env.update(env_overlay)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        print(f"FAILED: {label} exited with {completed.returncode}", file=sys.stderr)
        return False
    return True


def run_optional(label: str, command: Sequence[str]) -> bool:
    executable = command[0]
    if shutil.which(executable) is None:
        print(f"\n==> {label}")
        print(f"SKIPPED: {executable!r} is not available on PATH")
        return True
    return run(label, command)


def format_command(command: Sequence[str]) -> str:
    return " ".join(command)


if __name__ == "__main__":
    raise SystemExit(main())
