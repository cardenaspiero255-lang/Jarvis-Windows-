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
from pathlib import Path
import subprocess
import sys
import time

from startup_perf_gate import assess_windows_lite_samples

SENTINEL = "JARVIS_REAL_LITE_STARTUP="
MODEL = "Systran/faster-whisper-base"


async def worker_run(model_dir):
    from startup_resources import choose_plan, warm_voice_models
    plan = choose_plan(
        total_bytes=4 * 1024**3, available_bytes=2 * 1024**3,
        use_text=False, requested="auto"
    )
    if not (plan.mode == "lite" and plan.whisper and not plan.tts):
        raise RuntimeError("lite_policy_is_not_effective")
    from transcription import whisper_transcriber as tr

    async def load_whisper():
        await asyncio.to_thread(tr._get_model)

    async def never_preload_piper():
        raise RuntimeError("unexpected_piper_preload")

    statuses = await warm_voice_models(plan, load_whisper, never_preload_piper)
    if (statuses != {"whisper": "ready", "tts": "deferred"}
            or tr._model is None
            or "tts.tts_engine" in sys.modules):
        raise RuntimeError("actual_whisper_not_loaded_or_piper_preloaded")
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
    result = asyncio.run(worker_run(args.model_dir))
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
            raise RuntimeError("real_whisper_worker_failed")
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
    if (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows"):
        raise RuntimeError("disposable_windows_ci_only")

    from huggingface_hub import HfApi, snapshot_download
    api = HfApi()
    revision = api.model_info(MODEL).sha
    if not revision or len(revision) != 40:
        raise RuntimeError("model_commit_unknown")
    model_dir = Path(snapshot_download(
        repo_id=MODEL, revision=revision,
        allow_patterns=["model.bin", "config.json", "tokenizer.json",
                        "vocabulary.json", "preprocessor_config.json"],
    )).resolve()
    if not all((model_dir / name).is_file()
               for name in ("model.bin", "config.json", "tokenizer.json")):
        raise RuntimeError("offline_model_assets_incomplete")
    digest = hashlib.sha256((model_dir / "model.bin").read_bytes()).hexdigest()
    samples = [run_worker(sys.executable, model_dir, revision, digest)
               for _ in range(3)]
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
        "physical_four_gib_notebook_measured": False,
    }, sort_keys=True))
    sys.exit(0 if report["status"] == "LITE_STARTUP_WIN_CI_PASS" else 1)


if __name__ == "__main__":
    main()
