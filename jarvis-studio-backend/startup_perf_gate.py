"""Precommitted CI performance budgets for REAL JARVIS Whisper warm-up on Windows.

The simulated 4 GiB value is policy INPUT only. RSS and timings must come
from child processes actually executed on Windows. This does NOT certify
GUI ready time, acoustic latency, or behavior on a physical 4 GiB notebook.
"""
from __future__ import annotations

import math
import re
import statistics

STARTUP_BUDGET = {
    "peak_rss_mib": 1536.0,
    "whisper_ready_p95_ms": 90000,
    "full_worker_p95_ms": 105000,
}

def _p95(values):
    # Nearest-rank order statistic. With three runs, this is the worst run,
    # deliberately avoiding hiding a single severe regression in a median.
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def assess_windows_lite_samples(samples):
    """Fail closed for missing genuine inference, noisy data or over-budget."""
    errors = []
    if not isinstance(samples, list) or len(samples) != 3:
        return {"status": "NOT_CERTIFIED", "blockers": ["requires_three_processes"],
                "four_gib_physical_certified": False,
                "complete_gui_startup_certified": False}

    numerical = ["whisper_ready_ms", "full_worker_ms", "peak_rss_mib"]
    hashes = []
    revisions = []
    for index, case in enumerate(samples):
        if not isinstance(case, dict):
            errors.append("invalid_trial:" + str(index))
            continue
        if case.get("environment") != "github_hosted_windows":
            errors.append("not_windows_ci")
        if case.get("profile_simulated_ram_gib") != 4:
            errors.append("profile_not_4gib")
        if case.get("model_loaded") is not True or case.get("piper_preloaded") is not False:
            errors.append("model_or_profile_mismatch")
        sha = case.get("model_sha256")
        rev = case.get("model_revision")
        if not isinstance(sha, str) or not re.fullmatch("[a-f0-9]{64}", sha):
            errors.append("invalid_model_hash")
        else:
            hashes.append(sha)
        if not isinstance(rev, str) or not re.fullmatch("[a-f0-9]{40}", rev):
            errors.append("invalid_model_revision")
        else:
            revisions.append(rev)
        for name in numerical:
            value = case.get(name)
            if (type(value) not in (float, int)
                    or not math.isfinite(value) or value <= 0):
                errors.append("invalid_measurement:" + name)
        elapsed = case.get("full_worker_ms")
        ready = case.get("whisper_ready_ms")
        if (type(elapsed) in (float, int) and type(ready) in (float, int)
                and math.isfinite(elapsed) and math.isfinite(ready)
                and ready > elapsed):
            errors.append("timing_inconsistent")
    if len(set(hashes)) != 1 or len(set(revisions)) != 1:
        errors.append("different_model_assets")

    out = {
        "status": "NOT_CERTIFIED",
        "trials": len(samples),
        "blockers": sorted(set(errors)),
        "fixed_budget": dict(STARTUP_BUDGET),
        "four_gib_physical_certified": False,
        "complete_gui_startup_certified": False,
        "end_to_end_wake_latency_certified": False,
    }
    if errors:
        return out
    peak = max(x["peak_rss_mib"] for x in samples)
    ready = _p95([x["whisper_ready_ms"] for x in samples])
    end = _p95([x["full_worker_ms"] for x in samples])
    out.update({
        "peak_rss_mib_observed": peak,
        "whisper_ready_p50_ms": statistics.median(x["whisper_ready_ms"] for x in samples),
        "whisper_ready_p95_ms": ready,
        "full_worker_p95_ms": end,
        "model_sha256": hashes[0],
        "model_revision": revisions[0],
    })
    if peak > STARTUP_BUDGET["peak_rss_mib"]:
        errors.append("peak_memory_budget_exceeded")
    if ready > STARTUP_BUDGET["whisper_ready_p95_ms"]:
        errors.append("whisper_ready_latency_budget_exceeded")
    if end > STARTUP_BUDGET["full_worker_p95_ms"]:
        errors.append("total_worker_latency_budget_exceeded")
    out["blockers"] = sorted(set(errors))
    out["status"] = "LITE_STARTUP_WIN_CI_PASS" if not errors else "NOT_CERTIFIED"
    return out
