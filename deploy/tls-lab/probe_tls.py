from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Probe:
    name: str
    url: str
    verify: bool | str
    expected_ok: bool
    note: str


ROOT_CA = "/certs/top-secret-root-ca.pem"
RAG_LEAF = "/certs/rag.top.secret.cert.pem"
SELF_SIGNED_RAG = "/certs/selfsigned-rag.top.secret.cert.pem"


def main() -> None:
    probes = [
        Probe(
            "ragflow_root_ca",
            "https://rag.top.secret:8443/api/v1/datasets",
            ROOT_CA,
            True,
            "Root-CA vertraut der RAGFlow-Chain.",
        ),
        Probe(
            "seafile_root_ca",
            "https://seafile.top.secret:8443/api/v2.1/admin/libraries/",
            ROOT_CA,
            True,
            "Root-CA vertraut der Seafile-Chain.",
        ),
        Probe(
            "connector_proxy_root_ca",
            "https://connector.top.secret:8443/api/health",
            ROOT_CA,
            True,
            "Root-CA vertraut dem Connector-Proxy.",
        ),
        Probe(
            "ragflow_no_ca",
            "https://rag.top.secret:8443/api/v1/datasets",
            True,
            False,
            "Ohne interne CA muss die Verifikation fehlschlagen.",
        ),
        Probe(
            "ragflow_leaf_as_ca",
            "https://rag.top.secret:8443/api/v1/datasets",
            RAG_LEAF,
            False,
            "CA-signiertes Server-Leaf reicht im Connector-Container nicht als CA-Ersatz.",
        ),
        Probe(
            "ragflow_self_signed_leaf_as_ca",
            os.environ.get(
                "TLS_LAB_SELFSIGNED_URL",
                "https://selfsigned-rag.top.secret:8443/api/v1/datasets",
            ),
            SELF_SIGNED_RAG,
            True,
            "Self-signed Leaf kann als Trust-Anker funktionieren, bleibt aber Diagnose.",
        ),
        Probe(
            "ragflow_wrong_hostname",
            "https://wronghost.top.secret:8443/api/v1/datasets",
            ROOT_CA,
            False,
            "Server-Zertifikat enthaelt absichtlich SAN other.top.secret.",
        ),
        Probe(
            "expired_ragflow_root_ca",
            "https://expired-rag.top.secret:8443/api/v1/datasets",
            ROOT_CA,
            False,
            "Abgelaufenes Server-Zertifikat muss trotz Root-CA fehlschlagen.",
        ),
    ]

    failures = []
    for probe in probes:
        ok, detail = _run_probe(probe.url, probe.verify)
        status = "ok" if ok == probe.expected_ok else "unexpected"
        print(
            f"{status}: {probe.name}: expected_ok={probe.expected_ok} "
            f"actual_ok={ok} detail={detail} note={probe.note}",
            flush=True,
        )
        if ok != probe.expected_ok:
            failures.append(probe.name)
    if failures:
        raise SystemExit(f"TLS probe failures: {', '.join(failures)}")


def _run_probe(url: str, verify: bool | str) -> tuple[bool, str]:
    try:
        response = httpx.get(url, timeout=5, verify=verify, trust_env=False)
        return response.is_success, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


if __name__ == "__main__":
    main()
