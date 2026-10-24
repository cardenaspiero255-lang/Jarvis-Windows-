"""Measured startup of JARVIS' real Whisper voice backend on Windows CI.

Three fresh worker processes each load the *real* faster-whisper/base model;
RSS is sampled independently by the parent process (psutil). Asset download
is excluded from startup measurements and its resolved commit is captured.
A 4 GiB startup policy is simulated; the Windows runner is NOT RAM constrained.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

from startup_perf_gate import assess_windows_lite_samples

SENTINEL = "JARVIS_REAL_LITE_STARTUP="
MODEL = "Systran/faster-whisper-base"
CURRENT_PHASE = "created"


async def worker_run(model_dir):
    from startup_resources import choose_plan, warm_voice_models
    plan = choose_plan(
        total_bytes=4 * 1024**3, available_bytes=2 * 1024**3,
        use_text=False, requested="auto"
    )
    if not (plan.mode == "lite" and plan.whisper and not plan.tts):
        raise RuntimeError("lite_policy_is_not_effective")
    from transcription import whisper_transcriber as tr

    whisper_error_class = []
    async def load_whisper():
        try:
            await asyncio.to_thread(tr._get_model)
        except Exception as exc:
            whisper_error_class.append(type(exc).__name__)
            # Public runner only. Redact local paths and control characters
            # before exposing a short CTranslate2 diagnostic in GitHub CI.
            diagnostic = str(exc).replace("\r", " ").replace("\n", " ")
            diagnostic = re.sub(r"(?i)(?:[a-z]:\\\\|/)[^\\s]+", "<runtime_path>", diagnostic)
            diagnostic = "".join(ch for ch in diagnostic if ch.isprintable())
            print("JARVIS_WORKER_MODEL_ERROR=" + diagnostic[:220], flush=True)
            raise

    async def never_preload_piper():
        raise RuntimeError("unexpected_piper_preload")

    statuses = await warm_voice_models(plan, load_whisper, never_preload_piper)
    if statuses["whisper"] != "ready" or tr._model is None:
        kind = whisper_error_class[-1] if whisper_error_class else "no_model"
        raise RuntimeError("whisper_preload_unavailable_" + kind)
    if statuses["tts"] != "deferred" or "tts.tts_engine" in sys.modules:
        raise RuntimeError("piper_was_preloaded")
    # The whisper model is loaded from a pre-fetched local directory, never
    # re-downloaded during worker timing.
    if tr._bundled_model_path() != str(Path(model_dir).resolve()):
        raise RuntimeError("wrong_model_path")
    return {"model_loaded": True, "piper_preloaded": False,
            "profile_simulated_ram_gib": 4}


def child(args):
    if sys.platform != "win32":
        raise RuntimeError("windows_only")
    started = time.perf_counter()
    try:
        result = asyncio.run(worker_run(args.model_dir))
    except Exception as exc:
        # Never print full model paths or authentication details into public CI.
        print("JARVIS_WORKER_FAILURE_TYPE=" + type(exc).__name__, flush=True)
        code = str(exc)
        safe = ("whisper_preload_unavailable_", "piper_was_preloaded",
                "wrong_model_path", "lite_policy_is_not_effective")
        if type(exc) is RuntimeError and code.startswith(safe) and len(code) < 100:
            print("JARVIS_WORKER_FAILURE_CODE=" + code, flush=True)
        raise
    result["whisper_ready_ms"] = round((time.perf_counter() - started) * 1000)
    print(SENTINEL + json.dumps(result, sort_keys=True), flush=True)


def run_worker(parent_python, local_dir, rev, checksum):
    import psutil
    command = [parent_python, "-u", str(Path(__file__).resolve()),
               "--worker", "--model-dir", str(local_dir)]
    env = os.environ.copy()
    env["JARVIS_BUNDLED_WHISPER_MODEL"] = str(local_dir)
    env["HF_HUB_OFFLINE"] = "1"
    started = time.perf_counter()
    proc = subprocess.Popen(
        command, cwd=str(Path(__file__).resolve().parent),
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        tracker = psutil.Process(proc.pid)
        high_rss = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(proc.communicate)
            while not future.done():
                if time.perf_counter() - started > 120:
                    proc.kill()
                    raise TimeoutError("whisper_worker_timeout")
                try:
                    high_rss = max(high_rss, tracker.memory_info().rss)
                except psutil.Error:
                    pass
                time.sleep(0.025)
            output, _ = future.result(timeout=5)
        elapsed = round((time.perf_counter() - started) * 1000)
        records = [line[len(SENTINEL):] for line in output.splitlines()
                   if line.startswith(SENTINEL)]
        if proc.returncode != 0 or len(records) != 1:
            # Retain only a safe exception CLASS from the Windows child.
            reason = [line.partition("=")[2] for line in output.splitlines()
                      if line.startswith("JARVIS_WORKER_FAILURE_TYPE=")]
            error_class = reason[-1] if reason and reason[-1].isidentifier() else "unknown"
            for row in output.splitlines():
                if row.startswith("JARVIS_WORKER_MODEL_ERROR="):
                    print(row[:260], flush=True)
            failure_codes = [line.partition("=")[2] for line in output.splitlines()
                             if line.startswith("JARVIS_WORKER_FAILURE_CODE=")]
            safe = ("whisper_preload_unavailable_", "piper_was_preloaded",
                    "wrong_model_path", "lite_policy_is_not_effective")
            detail = failure_codes[-1] if (failure_codes
                     and failure_codes[-1].startswith(safe)
                     and len(failure_codes[-1]) < 100) else "unspecified"
            raise RuntimeError("real_whisper_worker_failed_" + error_class
                               + "_" + detail)
        result = json.loads(records[0])
        result.update({
            "environment": "github_hosted_windows",
            "full_worker_ms": elapsed,
            "peak_rss_mib": round(high_rss / 1024**2, 2),
            "model_sha256": checksum,
            "model_revision": rev,
        })
        return result
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def measured_campaign():
    global CURRENT_PHASE
    CURRENT_PHASE = "windows_environment"
    if (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows"):
        raise RuntimeError("disposable_windows_ci_only")

    from huggingface_hub import HfApi, snapshot_download
    api = HfApi()
    CURRENT_PHASE = "resolve_model_commit"
    revision = api.model_info(MODEL).sha
    if not revision or len(revision) != 40:
        raise RuntimeError("model_commit_unknown")
    CURRENT_PHASE = "download_pinned_model"
    model_dir = Path(snapshot_download(
        repo_id=MODEL, revision=revision,
        allow_patterns=["model.bin", "config.json", "tokenizer.json",
                        "vocabulary.json", "preprocessor_config.json"],
    )).resolve()
    CURRENT_PHASE = "verify_assets"
    if not all((model_dir / name).is_file()
               for name in ("model.bin", "config.json", "tokenizer.json")):
        raise RuntimeError("offline_model_assets_incomplete")
    digest = hashlib.sha256((model_dir / "model.bin").read_bytes()).hexdigest()
    samples = []
    for idx in range(3):
        CURRENT_PHASE = "real_model_worker_" + str(idx + 1)
        samples.append(run_worker(sys.executable, model_dir, revision, digest))
    CURRENT_PHASE = "fixed_gate"
    verdict = assess_windows_lite_samples(samples)
    return verdict, samples


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--worker", action="store_true")
    cli.add_argument("--model-dir")
    args = cli.parse_args()
    if args.worker:
        child(args)
        return
    report = {
        "schema": "jarvis-windows-lite-startup-perf-v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "status": "NOT_CERTIFIED",
        "source": "real_whisper_model_three_disposable_windows_processes",
        "physical_four_gib_notebook_measured": False,
        "installed_gui_startup_measured": False,
        "human_hey_jarvis_positives_measured": False,
    }
    try:
        gate, samples = measured_campaign()
        report["gate"] = gate
        report["samples"] = samples
        report["status"] = gate["status"]
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["failure_phase"] = CURRENT_PHASE
        message = str(exc)
        # Only whitelisted internal reason identifiers; never emit arbitrary
        # platform exceptions, paths or raw subprocess stdout into receipts.
        if (message.startswith("real_whisper_worker_failed_")
                or message in ("offline_model_assets_incomplete",
                               "model_commit_unknown", "disposable_windows_ci_only")):
            report["failure_code"] = message
        else:
            report["failure_code"] = "unexpected_" + type(exc).__name__
    root = os.environ.get("RUNNER_TEMP")
    if not root:
        raise RuntimeError("no_disposable_runner_temp")
    destination = Path(root) / "jarvis-windows-lite-startup-perf.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True),
                           encoding="utf-8")
    print("JARVIS_LITE_STARTUP_BENCHMARK=" + json.dumps({
        "status": report["status"],
        "peak_rss_mib": report.get("gate", {}).get("peak_rss_mib_observed"),
        "whisper_ready_p95_ms": report.get("gate", {}).get("whisper_ready_p95_ms"),
        "error_type": report.get("error_type", "none"),
        "failure_phase": report.get("failure_phase", "none"),
        "failure_code": report.get("failure_code", "none"),
        "physical_four_gib_notebook_measured": False,
    }, sort_keys=True))
    sys.exit(0 if report["status"] == "LITE_STARTUP_WIN_CI_PASS" else 1)


if __name__ == "__main__":
    main()
