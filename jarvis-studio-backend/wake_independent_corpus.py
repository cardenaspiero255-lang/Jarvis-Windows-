"""Frozen real-human speech negatives, externally recorded and CC0 per source.

Holdout only: do not train or tune openWakeWord on these clips.
The source's accent labels are estimates, not audited regional identities.
No generated/SAPI clips may count as independent human recordings.
"""
from __future__ import annotations

import math
import re

REQUIRED_SOURCE_COMMIT = "490cfbee850a6d409076f477c766f567000a79b6"
SOURCE_REPOSITORY = "OwenTyme/voice-zero"
FROZEN_PRODUCTION_THRESHOLD = 0.4

# Frozen BEFORE first inference, from the GitHub tree and sources at the
# commit above. The source voices/README.md carries reader and accent metadata.
FROZEN_NEGATIVE_MANIFEST = (
    {"speaker": "alana_jordan", "accent": "American, Midwest",
     "git_blob_sha": "99d89da29ff5289fc1282b61df3a615080140db9"},
    {"speaker": "andi", "accent": "American, Texas",
     "git_blob_sha": "7295de1c82e42427e5f6da8945301e8a88198d49"},
    {"speaker": "andy", "accent": "Scottish",
     "git_blob_sha": "f515705e8239e98a0aecaa43ba3d1bb8dccda700"},
    {"speaker": "annise", "accent": "Australian",
     "git_blob_sha": "2dd4f96e7980275b876da43ae64178a3a02ff775"},
    {"speaker": "anna_simon", "accent": "Dutch",
     "git_blob_sha": "18a6b4c5c7392fb470ab7a68a1f09120f5eed08e"},
    {"speaker": "delibab", "accent": "Northern Irish",
     "git_blob_sha": "ff86a28b29ff0eeb824262a027337efa64063e88"},
)
FROZEN_NEGATIVE_MANIFEST = tuple({
    **row,
    "source_repository": SOURCE_REPOSITORY,
    "source_commit": REQUIRED_SOURCE_COMMIT,
    "source_path": "voices/" + row["speaker"] + ".flac",
    "source_kind": "recorded_human",
    "license": "CC0-1.0",
    "label": "no_hey_jarvis",
    "accent_verified_independently": False,
} for row in FROZEN_NEGATIVE_MANIFEST)


def validate_manifest(cases) -> list[str]:
    problems = []
    if not isinstance(cases, (list, tuple)) or len(cases) < 6:
        return ["minimum_six_speakers_missing"]
    speakers = []
    accents = []
    paths = []
    for i, item in enumerate(cases):
        if not isinstance(item, dict):
            problems.append("invalid_record:" + str(i))
            continue
        speaker = item.get("speaker")
        accent = item.get("accent")
        path = item.get("source_path")
        if not isinstance(speaker, str) or not re.fullmatch(r"[a-z0-9_]+", speaker):
            problems.append("invalid_speaker")
        else:
            speakers.append(speaker)
        if not isinstance(accent, str) or not accent.strip():
            problems.append("missing_accent")
        else:
            accents.append(accent)
        if not isinstance(path, str) or path != "voices/" + str(speaker) + ".flac":
            problems.append("path_not_allowlisted")
        else:
            paths.append(path)
        if item.get("source_repository") != SOURCE_REPOSITORY:
            problems.append("source_repository_mismatch")
        if item.get("source_commit") != REQUIRED_SOURCE_COMMIT:
            problems.append("source_not_frozen")
        if not isinstance(item.get("git_blob_sha"), str) or not re.fullmatch(
            r"[0-9a-f]{40}", item["git_blob_sha"]):
            problems.append("invalid_git_blob_sha")
        if item.get("source_kind") != "recorded_human":
            problems.append("not_real_human")
        if item.get("license") != "CC0-1.0":
            problems.append("license_not_verified")
        if item.get("label") != "no_hey_jarvis":
            problems.append("not_negative")
        if item.get("accent_verified_independently") is not False:
            problems.append("accent_overclaim")
    if len(speakers) != len(set(speakers)) or len(paths) != len(set(paths)):
        problems.append("duplicate_speaker_or_path")
    if len(set(accents)) < 4:
        problems.append("insufficient_accents")
    return sorted(set(problems))


def adjudicate_negative_scores(cases, scores, threshold):
    blockers = validate_manifest(cases)
    if type(threshold) not in (int, float) or threshold != FROZEN_PRODUCTION_THRESHOLD:
        blockers.append("threshold_changed")
    speakers = [x.get("speaker") for x in cases if isinstance(x, dict)]
    if not isinstance(scores, dict) or set(scores) != set(speakers):
        blockers.append("incomplete_or_extraneous_scores")
        scores = scores if isinstance(scores, dict) else {}
    failures = []
    for speaker in speakers:
        value = scores.get(speaker)
        if (type(value) not in (int, float)
                or not math.isfinite(value) or not 0 <= value <= 1):
            blockers.append("invalid_score:" + str(speaker))
        elif value >= FROZEN_PRODUCTION_THRESHOLD:
            failures.append(speaker)
    if failures:
        blockers.append("false_activations:" + ",".join(sorted(failures)))
    return {
        "status": "NEGATIVE_HUMAN_CORPUS_PASS" if not blockers else "NOT_CERTIFIED",
        "blockers": sorted(set(blockers)),
        "real_human_speaker_count": len(set(speakers)),
        "accent_label_count": len({x.get("accent") for x in cases
                                   if isinstance(x, dict)}),
        "false_activation_count": len(failures),
        "false_activating_speakers": sorted(failures),
        "threshold": FROZEN_PRODUCTION_THRESHOLD,
        "independent_positive_corpus_certified": False,
        "entire_wake_acoustic_gate_certified": False,
        "physical_microphone_certified": False,
        "independently_verified_accent_labels": False,
    }
