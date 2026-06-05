#!/usr/bin/env python
"""Record the real logged-in Chrome demo flow for the connector.

The script intentionally records the existing Google Chrome window. It does not
create synthetic demo pages. It is meant for a manual late-night run or a
Codex automation run against already logged-in Seafile, RAGFlow, the connector
dashboard, and OpenWebUI tabs.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import shutil
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

_DEMO_IMPORT_ERRORS: dict[str, ModuleNotFoundError] = {}

try:
    import cv2  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without extra locally
    cv2 = None  # type: ignore[assignment]
    _DEMO_IMPORT_ERRORS["opencv-python"] = exc

try:
    import numpy as np  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without extra locally
    np = None  # type: ignore[assignment]
    _DEMO_IMPORT_ERRORS["numpy"] = exc

try:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without extra locally
    Image = ImageDraw = ImageFont = ImageGrab = None  # type: ignore[assignment]
    _DEMO_IMPORT_ERRORS["pillow"] = exc


IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - non-Windows safeguard for CLI checks and docs tooling
    USER32 = None
    KERNEL32 = None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010
SW_RESTORE = 9
SW_MAXIMIZE = 3
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_L = 0x4C
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", INPUT_UNION)]


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_id: int
    process_path: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def process_name(self) -> str:
        return Path(self.process_path).name.lower() if self.process_path else ""

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass
class Scene:
    name: str
    caption: str
    duration: float
    url: str | None = None
    js: str | None = None
    wait_after_action: float = 2.5
    click_input: bool = False
    prompt: str | None = None
    highlight: tuple[float, float, float, float] | None = None
    pointer: tuple[float, float] | None = None


def missing_demo_dependencies() -> list[str]:
    return sorted(_DEMO_IMPORT_ERRORS)


def ensure_windows() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Die Real-Chrome-Demo läuft nur unter Windows.")


def ensure_demo_dependencies() -> None:
    missing = missing_demo_dependencies()
    if not missing:
        return
    packages = ", ".join(missing)
    raise RuntimeError(
        "Fehlende Python-Abhängigkeiten für die Real-Chrome-Demo: "
        f"{packages}. Installiere sie mit "
        "`uv sync --locked --extra dev --extra demo-recording` oder starte den "
        "Befehl direkt mit "
        "`uv run --extra demo-recording python scripts/record_real_chrome_demo.py ...`."
    )


def refresh_process_path() -> None:
    if not IS_WINDOWS:
        return
    import winreg

    merged_entries: list[str] = []
    seen: set[str] = set()

    def add_path_entries(raw_path: str | None) -> None:
        if not raw_path:
            return
        for entry in raw_path.split(os.pathsep):
            normalized = entry.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged_entries.append(normalized)

    add_path_entries(os.environ.get("PATH"))
    machine_env = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with contextlib.suppress(OSError), winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        machine_env,
    ) as key:
        add_path_entries(winreg.QueryValueEx(key, "Path")[0])
    with contextlib.suppress(OSError), winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
    ) as key:
        add_path_entries(winreg.QueryValueEx(key, "Path")[0])
    if merged_entries:
        os.environ["PATH"] = os.pathsep.join(merged_entries)


def build_tool_report(repo_root: Path) -> dict[str, object]:
    refresh_process_path()
    commands = {name: shutil.which(name) for name in ("python", "uv", "git", "ffmpeg", "ffprobe")}
    notes: list[str] = []
    if commands["ffmpeg"] is None or commands["ffprobe"] is None:
        notes.append(
            "ffmpeg und ffprobe sollten für technische Videoprüfungen "
            "im Windows PATH liegen."
        )
    missing = missing_demo_dependencies()
    if missing:
        notes.append(
            "Python-Extras für die Real-Chrome-Demo fehlen. Nutze "
            "`uv sync --locked --extra dev --extra demo-recording`."
        )
    required_commands = ("ffmpeg", "ffprobe", "git", "uv", "python")
    return {
        "repo_root": str(repo_root),
        "python_executable": sys.executable,
        "commands": commands,
        "demo_python_dependencies": {
            "missing": missing,
            "ready": not missing,
        },
        "ready": not missing and all(commands[name] for name in required_commands),
        "notes": notes,
    }


def configure_dpi_awareness() -> None:
    ensure_windows()
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        with contextlib.suppress(Exception):
            USER32.SetProcessDPIAware()


def get_window_text(hwnd: int) -> str:
    ensure_windows()
    length = USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_process_path(pid: int) -> str:
    ensure_windows()
    handle = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wt.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return buffer.value if ok else ""
    finally:
        KERNEL32.CloseHandle(handle)


def enum_windows(include_tiny: bool = False) -> list[WindowInfo]:
    ensure_windows()
    windows: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not USER32.IsWindowVisible(hwnd):
            return True
        title = get_window_text(hwnd).strip()
        if not title:
            return True
        pid = wt.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = RECT()
        if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if not include_tiny and (width < 120 or height < 80):
            return True
        windows.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                process_id=int(pid.value),
                process_path=get_process_path(int(pid.value)),
                left=int(rect.left),
                top=int(rect.top),
                right=int(rect.right),
                bottom=int(rect.bottom),
            )
        )
        return True

    USER32.EnumWindows(callback, 0)
    return windows


def close_other_windows(log: list[dict[str, object]]) -> None:
    ensure_windows()
    keep_names = {
        "chrome.exe",
        "codex.exe",
        "codex desktop.exe",
        "code.exe",
    }
    for window in enum_windows():
        process_name = window.process_name
        if process_name in keep_names:
            continue
        if window.title in {"Program Manager"}:
            continue
        log.append({"closed_window": asdict(window)})
        USER32.PostMessageW(window.hwnd, WM_CLOSE, 0, 0)
    if log:
        time.sleep(3)


def find_chrome_window() -> WindowInfo:
    ensure_windows()
    candidates = [
        window
        for window in enum_windows(include_tiny=True)
        if window.process_name == "chrome.exe" and "chrome" in window.title.lower()
    ]
    if not candidates:
        candidates = [
            window
            for window in enum_windows(include_tiny=True)
            if window.process_name == "chrome.exe"
        ]
    if not candidates:
        raise RuntimeError("Kein sichtbares Google-Chrome-Fenster gefunden.")
    titled = [item for item in candidates if item.title.strip()]
    return max(titled or candidates, key=lambda item: (item.area, len(item.title)))


def activate_and_maximize(window: WindowInfo) -> WindowInfo:
    ensure_windows()
    USER32.ShowWindow(window.hwnd, SW_RESTORE)
    time.sleep(0.25)
    USER32.SetForegroundWindow(window.hwnd)
    time.sleep(0.25)
    USER32.ShowWindow(window.hwnd, SW_MAXIMIZE)
    time.sleep(1.0)
    refreshed = next(
        (item for item in enum_windows(include_tiny=True) if item.hwnd == window.hwnd),
        None,
    )
    if not refreshed:
        raise RuntimeError("Chrome-Fenster konnte nach Aktivierung nicht erneut gelesen werden.")
    return refreshed


def send_input(inputs: Iterable[INPUT]) -> None:
    ensure_windows()
    input_list = list(inputs)
    if not input_list:
        return
    array_type = INPUT * len(input_list)
    sent = USER32.SendInput(len(input_list), array_type(*input_list), ctypes.sizeof(INPUT))
    if sent != len(input_list):
        raise ctypes.WinError(ctypes.get_last_error())


def vk_input(vk: int, keyup: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if keyup else 0
    return INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)))


def unicode_input(char: str, keyup: bool = False) -> INPUT:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if keyup else 0)
    return INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(ki=KEYBDINPUT(0, ord(char), flags, 0, 0)),
    )


def press_vk(vk: int) -> None:
    send_input([vk_input(vk), vk_input(vk, keyup=True)])
    time.sleep(0.08)


def hotkey(*keys: int) -> None:
    events: list[INPUT] = []
    for key in keys:
        events.append(vk_input(key))
    for key in reversed(keys):
        events.append(vk_input(key, keyup=True))
    send_input(events)
    time.sleep(0.25)


def type_text(text: str, delay: float = 0.001) -> None:
    for char in text:
        send_input([unicode_input(char), unicode_input(char, keyup=True)])
        if delay:
            time.sleep(delay)


def click_window(window: WindowInfo, x: int, y: int) -> None:
    screen_x = window.left + x
    screen_y = window.top + y
    USER32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.1)
    send_input(
        [
            INPUT(
                type=INPUT_MOUSE,
                union=INPUT_UNION(
                    mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
                ),
            ),
            INPUT(
                type=INPUT_MOUSE,
                union=INPUT_UNION(
                    mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
                ),
            ),
        ]
    )
    time.sleep(0.4)


def navigate(window: WindowInfo, url: str) -> None:
    USER32.SetForegroundWindow(window.hwnd)
    time.sleep(0.15)
    hotkey(VK_CONTROL, VK_L)
    type_text(url)
    press_vk(VK_RETURN)


def run_bookmarklet(window: WindowInfo, javascript_body: str) -> None:
    script = "javascript:" + javascript_body
    USER32.SetForegroundWindow(window.hwnd)
    time.sleep(0.15)
    hotkey(VK_CONTROL, VK_L)
    type_text(script)
    press_vk(VK_RETURN)


def capture_chrome(window: WindowInfo, target_size: tuple[int, int]) -> Image.Image:
    refreshed = next((item for item in enum_windows() if item.hwnd == window.hwnd), window)
    raw = ImageGrab.grab(bbox=refreshed.rect, all_screens=True)
    if raw.size != target_size:
        raw = raw.resize(target_size, Image.Resampling.LANCZOS)
    return raw.convert("RGB")


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_names = ["segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf" if bold else "arial.ttf"]
    for name in font_names:
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
) -> None:
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=font)
    pad = 10
    draw.rounded_rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        radius=10,
        fill=(11, 18, 31, 220),
        outline=(79, 209, 197, 230),
        width=2,
    )
    draw.text((x, y), text, fill=(245, 250, 255, 255), font=font)


def overlay_frame(
    frame: Image.Image,
    scene: Scene,
    elapsed: float,
    scene_elapsed: float,
    total_duration: float,
) -> Image.Image:
    image = frame.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    title_font = load_font(max(22, int(width * 0.016)), bold=True)
    body_font = load_font(max(18, int(width * 0.013)))
    small_font = load_font(max(15, int(width * 0.010)))

    # Chapter caption.
    margin = max(18, int(width * 0.018))
    caption_lines = wrap_text(scene.caption, max(42, int(width / 27)))
    caption_height = 28 + len(caption_lines) * int(width * 0.018)
    box = (margin, height - caption_height - margin, width - margin, height - margin)
    draw.rounded_rectangle(
        box,
        radius=16,
        fill=(9, 13, 24, 218),
        outline=(67, 210, 201, 210),
        width=2,
    )
    draw.text((box[0] + 18, box[1] + 12), scene.name, fill=(101, 240, 222, 255), font=title_font)
    y = box[1] + 48
    for line in caption_lines:
        draw.text((box[0] + 18, y), line, fill=(238, 242, 248, 255), font=body_font)
        y += int(width * 0.020)

    # Progress bar.
    progress_width = width - 2 * margin
    progress = min(1.0, elapsed / max(total_duration, 0.1))
    bar_y = height - 8
    draw.rectangle((margin, bar_y, margin + progress_width, bar_y + 4), fill=(34, 43, 61, 210))
    draw.rectangle(
        (margin, bar_y, margin + int(progress_width * progress), bar_y + 4),
        fill=(80, 211, 197, 255),
    )

    if scene.highlight:
        x1, y1, x2, y2 = scale_box(scene.highlight, width, height)
        pulse = 0.65 + 0.35 * math.sin(scene_elapsed * 3.4)
        color = (87, 213, 196, int(175 + 55 * pulse))
        draw.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=color, width=5)

    if scene.pointer:
        px, py = int(scene.pointer[0] * width), int(scene.pointer[1] * height)
        draw.polygon(
            [(px, py), (px + 34, py + 12), (px + 13, py + 32)],
            fill=(255, 255, 255, 240),
            outline=(8, 12, 22, 255),
        )
        draw.ellipse((px + 22, py + 20, px + 34, py + 32), fill=(87, 213, 196, 245))

    timestamp = datetime.now().strftime("%H:%M:%S")
    draw_label(draw, (width - margin - 165, margin), timestamp, small_font)
    return Image.alpha_composite(image, overlay).convert("RGB")


def wrap_text(text: str, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if len(candidate) > limit and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:3]


def scale_box(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    return (
        int(box[0] * width),
        int(box[1] * height),
        int(box[2] * width),
        int(box[3] * height),
    )


def open_video_writer(
    path: Path,
    fps: float,
    size: tuple[int, int],
    codecs: list[str],
) -> cv2.VideoWriter:
    for codec in codecs:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if writer.isOpened():
            return writer
        writer.release()
    raise RuntimeError(f"Kein OpenCV-VideoWriter konnte für {path} geöffnet werden.")


def make_contact_sheet(frames: list[tuple[str, Image.Image]], output: Path) -> None:
    if not frames:
        return
    thumb_w, thumb_h = 480, 270
    cols = 2
    rows = math.ceil(len(frames) / cols)
    label_h = 44
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), (18, 23, 34))
    draw = ImageDraw.Draw(sheet)
    font = load_font(18, bold=True)
    for idx, (label, frame) in enumerate(frames):
        col = idx % cols
        row = idx // cols
        x = col * thumb_w
        y = row * (thumb_h + label_h)
        thumb = frame.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, y + label_h))
        draw.rectangle((x, y, x + thumb_w, y + label_h), fill=(11, 18, 31))
        draw.text((x + 12, y + 12), label[:58], fill=(240, 246, 252), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def validate_video(path: Path) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return result
    result["size_bytes"] = path.stat().st_size
    cap = cv2.VideoCapture(str(path))
    try:
        result["opened"] = bool(cap.isOpened())
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            result["fps"] = fps
            result["frame_count"] = frame_count
            result["duration_seconds"] = frame_count / fps if fps else 0
            result["width"] = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            result["height"] = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    finally:
        cap.release()
    return result


def scenes() -> list[Scene]:
    dashboard = "https://connector.top.secret/dashboard"
    return [
        Scene(
            name="Kapitel 1: Seafile als Quelle",
            url="https://seafile.top.secret/",
            duration=9,
            caption=(
                "Echte Seafile-Seite: Die Bibliothek bleibt die Quelle der "
                "Wahrheit, der Connector übernimmt danach die Zielartefakte."
            ),
            highlight=(0.00, 0.23, 0.34, 0.96),
            pointer=(0.08, 0.28),
        ),
        Scene(
            name="Kapitel 2: Connector Dashboard",
            url=dashboard,
            duration=9,
            caption=(
                "Echter Connector: Systemzustand, Erreichbarkeit und letzter "
                "Erfolg werden vor dem Workflow sichtbar geprüft."
            ),
            highlight=(0.18, 0.25, 0.73, 0.96),
            pointer=(0.55, 0.30),
        ),
        Scene(
            name="Kapitel 3: Prüfablauf",
            js="(()=>{document.querySelector('[data-tab=\"workflow\"]')?.click();})()",
            duration=10,
            caption=(
                "Keine manuelle RAGFlow-Anlage: Dataset, Dokumente, Chat und "
                "OpenWebUI-Pipe sind hier Connector-Schritte."
            ),
            highlight=(0.01, 0.46, 0.46, 0.84),
            pointer=(0.06, 0.48),
        ),
        Scene(
            name="Kapitel 4: Connector starten",
            js="(()=>{document.getElementById('workflow-run')?.click();})()",
            duration=28,
            wait_after_action=1.0,
            caption=(
                "Connector übernimmt Initialisierung und Synchronisation; die "
                "Ausgabe zeigt, was erzeugt oder wiederverwendet wurde."
            ),
            highlight=(0.18, 0.40, 0.78, 0.92),
            pointer=(0.33, 0.39),
        ),
        Scene(
            name="Kapitel 5: Sync-Läufe",
            js="(()=>{document.querySelector('[data-tab=\"syncs\"]')?.click();})()",
            duration=10,
            caption=(
                "Der Sync-Verlauf zeigt Status, Laufzeiten und Ergebnisdetails "
                "des automatischen Connector-Laufs."
            ),
            highlight=(0.17, 0.32, 0.95, 0.92),
            pointer=(0.06, 0.54),
        ),
        Scene(
            name="Kapitel 6: Änderungen",
            js="(()=>{document.querySelector('[data-tab=\"changes\"]')?.click();})()",
            duration=12,
            caption=(
                "Änderungen belegen die Zielaktionen: RAGFlow-Dataset, "
                "RAGFlow-Chat sowie OpenWebUI-Tool und Pipe."
            ),
            highlight=(0.17, 0.32, 0.96, 0.92),
            pointer=(0.06, 0.60),
        ),
        Scene(
            name="Kapitel 7: Systeme",
            js="(()=>{document.querySelector('[data-tab=\"systems\"]')?.click();})()",
            duration=10,
            caption=(
                "Systeme verknüpft Seafile-Bibliotheken mit den automatisch "
                "bekannten RAGFlow-Datasets."
            ),
            highlight=(0.17, 0.32, 0.96, 0.92),
            pointer=(0.06, 0.71),
        ),
        Scene(
            name="Kapitel 8: OpenWebUI-Mapping",
            js="(()=>{document.querySelector('[data-tab=\"openwebui\"]')?.click();})()",
            duration=13,
            caption=(
                "OpenWebUI-Integration: Der Connector macht Chat, Tool, Pipe "
                "und Modellzuordnung sichtbar."
            ),
            highlight=(0.17, 0.32, 0.96, 0.92),
            pointer=(0.06, 0.77),
        ),
        Scene(
            name="Kapitel 9: RAGFlow-Ergebnis",
            url="https://rag.top.secret/",
            duration=14,
            caption=(
                "RAGFlow zeigt das automatisch angelegte Dataset und den "
                "automatisch angelegten Chat nach dem Connector-Lauf."
            ),
            highlight=(0.12, 0.24, 0.92, 0.88),
            pointer=(0.20, 0.34),
        ),
        Scene(
            name="Kapitel 10: OpenWebUI-Pipe",
            url="https://openwebui.top.secret/",
            duration=9,
            caption=(
                "OpenWebUI nutzt die automatisch erzeugte Seafile-Pipe als "
                "Modell für den Chat mit synchronisierten Inhalten."
            ),
            highlight=(0.03, 0.23, 0.67, 0.33),
            pointer=(0.55, 0.25),
        ),
        Scene(
            name="Kapitel 11: Frage an die Pipe",
            click_input=True,
            prompt=(
                "Welche Rolle übernimmt der Seafile-RAGFlow-Connector, und wo "
                "sieht man, dass Dataset, Chat und OpenWebUI-Pipe automatisch "
                "erzeugt werden?"
            ),
            duration=46,
            wait_after_action=0.5,
            caption=(
                "Die Frage wird in OpenWebUI an genau diese Pipe gestellt; die "
                "Antwort soll den Connector-Ablauf nachvollziehbar machen."
            ),
            highlight=(0.27, 0.52, 0.77, 0.66),
            pointer=(0.30, 0.56),
        ),
        Scene(
            name="Kapitel 12: Abschlusskontrolle",
            url=dashboard,
            js="(()=>{document.querySelector('[data-tab=\"openwebui\"]')?.click();})()",
            duration=8,
            wait_after_action=2.0,
            caption=(
                "Endzustand: Dashboard, RAGFlow und OpenWebUI zeigen den "
                "automatisch erzeugten und nutzbaren Workflow."
            ),
            highlight=(0.17, 0.32, 0.96, 0.92),
            pointer=(0.06, 0.77),
        ),
    ]


def record(args: argparse.Namespace) -> dict[str, object]:
    ensure_windows()
    ensure_demo_dependencies()
    configure_dpi_awareness()
    repo_root = Path(args.repo_root).resolve()
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = repo_root / "output" / "demo-recording" / f"real-chrome-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    docs_demo = repo_root / "docs" / "assets" / "demo"
    artifacts = repo_root / "artifacts"
    docs_demo.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    log: list[dict[str, object]] = []
    if args.close_other_windows:
        close_other_windows(log)

    chrome = activate_and_maximize(find_chrome_window())
    size = (chrome.width, chrome.height)
    if size[0] < 900 or size[1] < 600:
        raise RuntimeError(f"Chrome-Fenster ist zu klein für eine saubere Aufnahme: {size}")

    if args.dry_run:
        first = capture_chrome(chrome, size)
        first_path = run_dir / "dry-run-chrome.png"
        first.save(first_path)
        return {
            "status": "dry-run",
            "chrome": asdict(chrome),
            "screenshot": str(first_path),
            "closed_windows": log,
        }

    fps = float(args.fps)
    mkv_path = docs_demo / "seafile-ragflow-connector-demo.mkv"
    mp4_path = docs_demo / "seafile-ragflow-connector-demo.mp4"
    poster_path = docs_demo / "seafile-ragflow-connector-demo-poster.jpg"
    contact_path = artifacts / "demo-recording-contact-sheet.jpg"

    mkv_writer = open_video_writer(mkv_path, fps, size, ["mp4v", "XVID", "MJPG"])
    mp4_writer = open_video_writer(mp4_path, fps, size, ["mp4v", "avc1", "H264"])
    contact_frames: list[tuple[str, Image.Image]] = []
    poster_saved = False
    scene_list = scenes()
    total_duration = sum(scene.duration + scene.wait_after_action for scene in scene_list)
    elapsed = 0.0
    frame_period = 1.0 / fps

    try:
        for scene in scene_list:
            chrome = activate_and_maximize(find_chrome_window())
            if scene.url:
                navigate(chrome, scene.url)
                time.sleep(scene.wait_after_action)
                elapsed += scene.wait_after_action
            if scene.js:
                run_bookmarklet(chrome, scene.js)
                time.sleep(scene.wait_after_action)
                elapsed += scene.wait_after_action
            if scene.click_input and scene.prompt:
                # OpenWebUI prompt box is centered in the real page. The click is
                # proportional to the Chrome window to remain stable across DPI.
                click_window(chrome, int(size[0] * 0.43), int(size[1] * 0.56))
                type_text(scene.prompt)
                press_vk(VK_RETURN)
                time.sleep(scene.wait_after_action)
                elapsed += scene.wait_after_action

            scene_start = time.monotonic()
            sample_taken = False
            while time.monotonic() - scene_start < scene.duration:
                loop_start = time.monotonic()
                raw = capture_chrome(chrome, size)
                scene_elapsed = time.monotonic() - scene_start
                rendered = overlay_frame(raw, scene, elapsed, scene_elapsed, total_duration)
                if not poster_saved:
                    rendered.save(poster_path, quality=92)
                    poster_saved = True
                if not sample_taken and len(contact_frames) < len(scene_list):
                    contact_frames.append((scene.name, rendered.copy()))
                    sample_taken = True
                frame = cv2.cvtColor(np.array(rendered), cv2.COLOR_RGB2BGR)
                mkv_writer.write(frame)
                mp4_writer.write(frame)
                elapsed += frame_period
                sleep_for = frame_period - (time.monotonic() - loop_start)
                if sleep_for > 0:
                    time.sleep(sleep_for)
    finally:
        mkv_writer.release()
        mp4_writer.release()

    make_contact_sheet(contact_frames, contact_path)
    report = {
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
        "chrome": asdict(chrome),
        "closed_windows": log,
        "outputs": {
            "mkv": validate_video(mkv_path),
            "mp4": validate_video(mp4_path),
            "poster": str(poster_path),
            "contact_sheet": str(contact_path),
        },
        "scenes": [asdict(scene) for scene in scene_list],
    }
    report_path = run_dir / "recording-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "SUCCESS.txt").write_text("completed\n", encoding="utf-8")
    return report | {"report_path": str(report_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--close-other-windows", action="store_true")
    parser.add_argument("--check-tools", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check_tools:
        report = build_tool_report(Path(args.repo_root).resolve())
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ready"] else 1
    try:
        result = record(args)
    except Exception as exc:
        failure_dir = Path(args.repo_root).resolve() / "output" / "demo-recording"
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_path = failure_dir / "real-chrome-recording-failure.json"
        failure_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                    "time": datetime.now(UTC).isoformat(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
