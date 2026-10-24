"""Frozen human hard-negative benchmark and fail-closed comparison contracts.

All 16 external clips, splits and Git blob identities were frozen BEFORE running
this model benchmark. The real speaker identities of the original Picovoice
benchmark clips are not provided, so speaker-disjointness is NOT certified.
"""
from __future__ import annotations

import math
import re

SOURCE_REPO = "Picovoice/wake-word-benchmark"
SOURCE_COMMIT = "84919190fb1891bf0936dcb577d9268e467f876f"
PRODUCTION_THRESHOLD = 0.4
_SOURCE_ROWS = [
  {
    "source_path": "audio/jarvis/008a6329-b20c-4cfc-9ad4-9e7034bc5148.wav",
    "git_blob_sha": "23c4543e907b06d1234faf206f9ba4db8b5f260b",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/112d3b6b-4836-4752-b8df-9d649a65ee04.wav",
    "git_blob_sha": "4ac8797f21c7a719ab76a4c3af3a594ef635487d",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/24b24ac6-23b3-46ab-96e4-ff1dea6fc455.wav",
    "git_blob_sha": "088988ebbc256c65981ecc879210e6a33e586b43",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/368172e4-2259-4a33-a18e-9e5f4e6f3057.wav",
    "git_blob_sha": "ec64ef0b8b3f90bef166a40b1382c615093fe2de",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/4c157278-ae58-4de1-b441-651df95484e9.wav",
    "git_blob_sha": "7a50ee9912b6e677e3e0d73c058ffa019c10f3d6",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/61723bdf-d44c-4b30-b5e0-69682bf28189.wav",
    "git_blob_sha": "a1c88159b20f163c95fd57bb35531c543bc57afa",
    "phrase": "jarvis",
    "split": "development"
  },
  {
    "source_path": "audio/jarvis/73a2922e-6dce-40ff-a0a4-6c05a0c0cd67.wav",
    "git_blob_sha": "779c20cbee4fe83b1a4c8b9dcfe4f9e2def4fa11",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/jarvis/88880097-3259-44de-89b5-7ddb17c081a4.wav",
    "git_blob_sha": "8b049d8bc52e0662636eff27041b3d416ab29822",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/jarvis/a4d55a7c-bcbc-4ec1-82bc-72c779c96561.wav",
    "git_blob_sha": "b7c36337cbd62b505c68b43e64d00017d253e8bf",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/jarvis/b4a52157-0083-4bf9-83bd-bf33398d1da0.wav",
    "git_blob_sha": "d8abfe6ce5a1c4a8bf8f010cdb339109b70bfea2",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/jarvis/caab5aa6-2751-4a84-809a-1e9b714807a9.wav",
    "git_blob_sha": "5f2a112c08cfe84feffe689f526b935323529dee",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/jarvis/e2e80bb5-f007-4294-9c5e-da1dd5783c59.wav",
    "git_blob_sha": "7bfcaa1ee9b0ecfae86c400eaefb167abdf729e2",
    "phrase": "jarvis",
    "split": "holdout"
  },
  {
    "source_path": "audio/computer/0386da81-9db7-499c-b4f8-910beec53c23.wav",
    "git_blob_sha": "ba9683205dadc5eb5294cfb8f3f963aa8ed6b0ee",
    "phrase": "computer",
    "split": "development"
  },
  {
    "source_path": "audio/computer/39832a2e-694f-4e8c-a00c-3f429b8dda14.wav",
    "git_blob_sha": "6f0d67a0b058acd15ab5d91962f0f9c3f26ac542",
    "phrase": "computer",
    "split": "holdout"
  },
  {
    "source_path": "audio/alexa/0.flac",
    "git_blob_sha": "7890f217d0aecdd67fdb53a09a1c5d1328fb06d2",
    "phrase": "alexa",
    "split": "development"
  },
  {
    "source_path": "audio/alexa/189.flac",
    "git_blob_sha": "5af45bc2f7540874449f1f0e650e04b6cc647f41",
    "phrase": "alexa",
    "split": "holdout"
  }
]
FROZEN_SAMPLES = tuple({
    **row,
    "label": "hard_negative",  # A spoken "Jarvis" is NOT "Hey Jarvis".
    "source_kind": "human_recording",
    "source_repo": SOURCE_REPO,
    "source_commit": SOURCE_COMMIT,
    "license": "Apache-2.0",
    "speaker_identity_verified": False,
} for row in _SOURCE_ROWS)


def validate_manifest(cases):
    errors = []
    if not isinstance(cases, (list, tuple)) or len(cases) != len(FROZEN_SAMPLES):
        return ["invalid_frozen_inventory"]
    if (len({r.get("source_path") for r in cases if isinstance(r, dict)}) != 16
            or len({r.get("git_blob_sha") for r in cases if isinstance(r, dict)}) != 16):
        errors.append("duplicate_source_or_blob")
    for actual, expected in zip(cases, FROZEN_SAMPLES):
        if not isinstance(actual, dict) or actual != expected:
            errors.append("source_provenance_or_label_changed")
    if sum(r.get("split") == "development" for r in cases if isinstance(r, dict)) != 8:
        errors.append("development_split_changed")
    if sum(r.get("split") == "holdout" for r in cases if isinstance(r, dict)) != 8:
        errors.append("holdout_split_changed")
    if len({r.get("phrase") for r in cases if isinstance(r, dict)}) != 3:
        errors.append("hard_negative_phrase_coverage")
    for case in cases:
        if not isinstance(case, dict):
            continue
        path = case.get("source_path")
        digest = case.get("git_blob_sha")
        if (not isinstance(path, str)
                or not re.fullmatch(r"audio/(jarvis|computer|alexa)/[a-z0-9.-]+\.(wav|flac)", path)):
            errors.append("unsafe_or_unexpected_path")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{40}", digest):
            errors.append("bad_blob_hash")
    return sorted(set(errors))


def score_negative_comparison(baseline, verified, threshold):
    if (type(threshold) not in (int, float)
            or threshold != PRODUCTION_THRESHOLD
            or not isinstance(baseline, list)
            or not isinstance(verified, list)
            or not baseline or len(baseline) != len(verified)):
        return {"status": "NOT_CERTIFIED", "errors": ["invalid_input"]}
    if any(type(s) not in (int, float) or not math.isfinite(s) or not 0 <= s <= 1
           for s in baseline) or any(type(v) is not bool for v in verified):
        return {"status": "NOT_CERTIFIED", "errors": ["invalid_score_or_verdict"]}
    if any(v and s < threshold for s, v in zip(baseline, verified)):
        return {"status": "NOT_CERTIFIED", "errors": ["verifier_trigger_without_baseline"]}
    base_fp = sum(score >= threshold for score in baseline)
    verified_fp = sum(verified)
    return {
        "status": "NEGATIVE_COMPARISON_MEASURED",
        "evaluated_clips": len(baseline),
        "baseline_false_activations": base_fp,
        "verified_false_activations": verified_fp,
        "baseline_fpr_per_clip": base_fp / len(baseline),
        "verified_fpr_per_clip": verified_fp / len(baseline),
        "false_reject_rate_certified": False,
        "speaker_independent_certified": False,
        "positive_human_corpus_certified": False,
    }


def classification_metrics(*, negatives, baseline_fp, verified_fp,
                           real_positives, baseline_tp, verified_tp):
    values = (negatives, baseline_fp, verified_fp,
              real_positives, baseline_tp, verified_tp)
    if (any(type(v) is not int or v < 0 for v in values)
            or negatives == 0
            or baseline_fp > negatives or verified_fp > baseline_fp
            or baseline_tp > real_positives or verified_tp > real_positives):
        raise ValueError("invalid_confusion_matrix")
    return {
        "baseline_fpr_per_clip": baseline_fp / negatives,
        "verified_fpr_per_clip": verified_fp / negatives,
        "baseline_fnr": ((real_positives - baseline_tp) / real_positives
                         if real_positives else None),
        "verified_fnr": ((real_positives - verified_tp) / real_positives
                         if real_positives else None),
        "false_alarms_per_hour_certified": False,
        "real_positive_samples": real_positives,
    }


def verify_real_positive_intake(records):
    """Validate metadata ONLY; never assert audio authenticity from metadata."""
    if not isinstance(records, list) or len(records) < 2:
        return ["need_development_and_holdout_positives"]
    errors = []
    speakers = {"development": set(), "holdout": set()}
    hashes = set()
    for r in records:
        if not isinstance(r, dict):
            errors.append("invalid_record")
            continue
        split = r.get("split")
        speaker = r.get("speaker_id")
        digest = r.get("clip_sha256")
        if split not in speakers:
            errors.append("invalid_split")
            continue
        if not isinstance(speaker, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{3,80}", speaker):
            errors.append("invalid_speaker_id")
            continue
        speakers[split].add(speaker)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            errors.append("invalid_audio_sha256")
        elif digest in hashes:
            errors.append("duplicate_audio")
        else:
            hashes.add(digest)
        if r.get("phrase") != "hey jarvis":
            errors.append("not_exact_positive_phrase")
        if r.get("source_kind") != "recorded_human":
            errors.append("synthetic_or_unknown_audio")
        if r.get("consent") != "explicit_research_use":
            errors.append("no_recorded_consent")
        if r.get("verification") != "human_audio_and_transcript_review":
            errors.append("no_manual_phrase_review")
        if r.get("license") not in ("CC0-1.0", "CC-BY-4.0", "Apache-2.0"):
            errors.append("license_unknown")
        if not isinstance(r.get("source_set"), str) or not r["source_set"].strip():
            errors.append("source_unknown")
    if not all(speakers.values()):
        errors.append("missing_split")
    if speakers["development"] & speakers["holdout"]:
        errors.append("speaker_leakage")
    return sorted(set(errors))
