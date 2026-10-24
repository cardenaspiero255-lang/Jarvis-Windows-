"""Memory-aware, dependency-free startup warm-up policy for JARVIS Windows.

Keeps the installed application responsive on small notebooks: never preload
both ONNX voice engines concurrently. Under pressure defer all eager work.
A deferred model remains available for genuine on-demand use.

No performance claim is made before a physical hardware benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import sys

GIB = 1024 ** 3
MIB = 1024 ** 2
LITE_TOTAL_MAX = 5 * GIB
LITE_AVAILABLE_MAX = 2 * GIB
CRITICAL_AVAILABLE_MAX = 1024 * MIB


@dataclass(frozen=True)
class StartupPlan:
    mode: str
    whisper: bool
    tts: bool
    reason: str


def get_windows_memory_bytes() -> tuple[int, int] | None:
    """Read *current* physical RAM and free RAM through native Win32, or None.

    Does not estimate available RAM from total RAM or use a test default as a
    measured value. Works in frozen Python and with no psutil dependency.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        total, available = int(status.ullTotalPhys), int(status.ullAvailPhys)
        if total <= 0 or not 0 <= available <= total:
            return None
        return total, available
    except (AttributeError, OSError, ValueError):
        return None


def choose_plan(*, total_bytes: int | None, available_bytes: int | None,
                use_text: bool, requested: str = "auto") -> StartupPlan:
    """Pure startup decision. No microphone, network, disk, model or audio I/O."""
    preference = requested.strip().lower() if isinstance(requested, str) else "auto"
    if preference not in ("auto", "lite", "normal"):
        preference = "auto"
    valid_total = (type(total_bytes) is int and total_bytes > 0)
    valid_available = (type(available_bytes) is int and available_bytes >= 0)
    measured = valid_total and valid_available and available_bytes <= total_bytes
    auto_lite = bool(
        measured and (total_bytes <= LITE_TOTAL_MAX
                      or available_bytes <= LITE_AVAILABLE_MAX)
    )
    mode = ("lite" if auto_lite else "normal") if preference == "auto" else preference
    low_pressure = bool(measured and available_bytes < CRITICAL_AVAILABLE_MAX)
    tiny_machine = bool(measured and total_bytes < 3 * GIB)
    # On a 4-GiB notebook, warm STT for voice mode so the first verified wake
    # is usable, but let neural TTS load lazily. At critically low *free* memory,
    # even Whisper should remain lazy to avoid an out-of-memory startup.
    whisper = not use_text and not low_pressure and not tiny_machine
    tts = mode == "normal" and not low_pressure
    return StartupPlan(
        mode=mode, whisper=whisper, tts=tts,
        reason=("critical_memory" if low_pressure or tiny_machine
                else "lite_device" if mode == "lite"
                else "sequential_normal")
    )


async def warm_voice_models(plan: StartupPlan, whisper_loader, tts_loader) -> dict[str, str]:
    """Await one preloader at a time without blocking the caller's event loop.

    Errors must leave JARVIS running and allow the other backend to be warmed.
    The individual loaders implement their own asynchronous thread delegation.
    """
    statuses: dict[str, str] = {"whisper": "deferred", "tts": "deferred"}
    for name, enabled, loader in (
        ("whisper", plan.whisper, whisper_loader),
        ("tts", plan.tts, tts_loader),
    ):
        if not enabled:
            continue
        try:
            await loader()
        except Exception as exc:
            statuses[name] = "unavailable"
            print(f"[Startup] {name} preload deferred after {type(exc).__name__}", flush=True)
        else:
            statuses[name] = "ready"
    return statuses


def plan_for_current_windows(*, use_text: bool) -> StartupPlan:
    actual = get_windows_memory_bytes()
    total, free = actual if actual is not None else (None, None)
    return choose_plan(
        total_bytes=total, available_bytes=free, use_text=use_text,
        requested=os.environ.get("JARVIS_STARTUP_PROFILE", "auto"),
    )
