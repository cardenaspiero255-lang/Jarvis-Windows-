"""Local-only collection and review ledger for human 'Hey Jarvis' positives.

Consent and human authenticity cannot be established from metadata. No cloud,
model scoring, training, or GitHub upload is performed by this tool.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import wave

VALID_SPLITS = frozenset(("development", "holdout"))
VALID_CONDITIONS = frozenset(("quiet", "fan", "traffic", "far_field"))
VALID_DISTANCES = frozenset(("near", "medium", "far"))
ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{6,80}\Z")
ACCENT_PATTERN = re.compile(r"[a-zA-Z]{2,3}-[a-zA-Z0-9]{2,10}\Z")
MANIFEST_NAME = "manifest.private.json"
WAVE_MAX_BYTES = 400_000


def _private_root(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    repo = Path(__file__).resolve().parent.parent
    if root == repo or repo in root.parents:
        raise ValueError("private corpus must be outside Git repository")
    return root


def _load(root: Path) -> dict:
    path = root / MANIFEST_NAME
    if path.is_symlink():
        raise ValueError("unsafe manifest symlink")
    if not path.exists():
        return {"schema": 1, "samples": [], "sealed_manifest_sha256": None}
    obj = json.loads(path.read_text("utf-8"))
    if (not isinstance(obj, dict) or obj.get("schema") != 1
            or not isinstance(obj.get("samples"), list)
            or "sealed_manifest_sha256" not in obj):
        raise ValueError("private manifest schema invalid")
    return obj


def _sample_digest(items: list) -> str:
    payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_archive(root: Path, state: dict) -> None:
    for item in state["samples"]:
        if not isinstance(item, dict):
            raise ValueError("invalid saved record")
        name = item.get("filename")
        if not isinstance(name, str) or not re.fullmatch(r"[a-f0-9]{32}\.wav", name):
            raise ValueError("invalid stored file path")
        file = root / "audio" / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("stored WAV missing or symlink")
        if hashlib.sha256(file.read_bytes()).hexdigest() != item.get("sha256"):
            raise ValueError("stored WAV tampered")
    seal = state["sealed_manifest_sha256"]
    if seal is not None and (not isinstance(seal, str) or
                             _sample_digest(state["samples"]) != seal):
        raise ValueError("sealed manifest tampered")


def _save(root: Path, state: dict) -> None:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, root / MANIFEST_NAME)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _inspect_pcm(path: Path) -> tuple[bytes, float]:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".wav":
        raise ValueError("expected an ordinary local WAV file")
    if path.stat().st_size < 1000 or path.stat().st_size > WAVE_MAX_BYTES:
        raise ValueError("WAV size outside allowed limits")
    try:
        with wave.open(str(path), "rb") as wav:
            if (wav.getnchannels() != 1 or wav.getframerate() != 16000
                    or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE"):
                raise ValueError("expected PCM16 mono 16 kHz")
            frames = wav.getnframes()
            if not 16000 <= frames <= 160000:
                raise ValueError("WAV must contain 1-10 seconds")
            pcm = wav.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise ValueError("invalid WAV structure") from exc
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    rms = math.sqrt(sum(int(x) ** 2 for x in samples) / len(samples))
    if rms < 60:
        raise ValueError("silent/near-silent clip")
    return path.read_bytes(), rms


def ingest_wav(root: Path, wav_path: Path, *, speaker_id: str, split: str,
               accent: str, condition: str, distance: str,
               consent_attested: bool, reviewed_exact_phrase: bool,
               source_kind: str = "recorded_human") -> dict:
    """Imports only after explicit operator consent AND manual audio review."""
    if (not isinstance(speaker_id, str) or not ID_PATTERN.fullmatch(speaker_id)
            or not isinstance(accent, str) or not ACCENT_PATTERN.fullmatch(accent)
            or split not in VALID_SPLITS or condition not in VALID_CONDITIONS
            or distance not in VALID_DISTANCES
            or consent_attested is not True
            or reviewed_exact_phrase is not True
            or source_kind != "recorded_human"):
        raise ValueError("invalid metadata, consent, human origin or phrase review")
    root = _private_root(root)
    payload, rms = _inspect_pcm(Path(wav_path))
    digest = hashlib.sha256(payload).hexdigest()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = root / ".intake.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("private intake locked; do not run two writers") from exc
    out = None
    try:
        os.close(lock_fd)
        state = _load(root)
        _verify_archive(root, state)
        if state["sealed_manifest_sha256"] is not None:
            raise ValueError("sealed holdout: no changes allowed")
        if any(row["sha256"] == digest for row in state["samples"]):
            raise ValueError("duplicate audio SHA256")
        if any(row["speaker_id"] == speaker_id and row["split"] != split
               for row in state["samples"]):
            raise ValueError("speaker leakage across splits")
        (root / "audio").mkdir(mode=0o700, exist_ok=True)
        name = secrets.token_hex(16) + ".wav"
        out = root / "audio" / name
        # Exclusive creation prevents accidental overwrite of a private recording.
        with out.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        state["samples"].append({
            "filename": name, "sha256": digest, "speaker_id": speaker_id,
            "split": split, "accent": accent, "condition": condition,
            "distance": distance, "phrase": "hey jarvis",
            "source_kind": "recorded_human",
            "consent": "explicit_research_use",
            "verification": "operator_manual_audio_and_transcript_review",
            "rights": "private-evaluation-only",
            "audio_rms": round(rms, 1),
        })
        _save(root, state)
    except Exception:
        if out is not None:
            out.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return {"status": "PRIVATE_SAMPLE_INGESTED",
            "human_authenticity_certified": False,
            "release_certified": False,
            "model_accuracy_certified": False}


def corpus_summary(root: Path) -> dict:
    root = _private_root(root)
    state = _load(root)
    _verify_archive(root, state)
    speakers = {split: set() for split in VALID_SPLITS}
    clips = {split: 0 for split in VALID_SPLITS}
    conditions = {split: set() for split in VALID_SPLITS}
    for sample in state["samples"]:
        split = sample.get("split")
        if split not in VALID_SPLITS:
            raise ValueError("invalid split in archive")
        speakers[split].add(sample["speaker_id"])
        clips[split] += 1
        conditions[split].add(sample["condition"])
    if speakers["development"] & speakers["holdout"]:
        raise ValueError("speaker leakage in archive")
    sufficient = all(
        len(speakers[split]) >= 3 and clips[split] >= 9
        and len(conditions[split]) >= 3
        for split in VALID_SPLITS
    )
    seal = state["sealed_manifest_sha256"]
    return {
        "status": ("PRIVATE_HOLDOUT_SEALED" if seal
                   else "PRIVATE_CORPUS_READY_TO_SEAL" if sufficient
                   else "NOT_CERTIFIED"),
        "clips": len(state["samples"]),
        "counts_by_split": clips,
        "speaker_counts_by_split": {s: len(ids) for s, ids in speakers.items()},
        "condition_counts_by_split": {s: len(ids) for s, ids in conditions.items()},
        "false_reject_rate": None,
        "speaker_independence_certified": False,
        "human_authenticity_certified": False,
        "commercial_rights_certified": False,
        "holdout_released_to_model": False,
    }


def seal_holdout(root: Path) -> dict:
    root = _private_root(root)
    report = corpus_summary(root)
    if report["status"] != "PRIVATE_CORPUS_READY_TO_SEAL":
        raise ValueError("requires 3 speakers / 9 clips / 3 conditions per split")
    lock = root / ".intake.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("private intake locked") from exc
    try:
        os.close(fd)
        state = _load(root)
        _verify_archive(root, state)
        if state["sealed_manifest_sha256"] is not None:
            raise ValueError("already sealed")
        state["sealed_manifest_sha256"] = _sample_digest(state["samples"])
        _save(root, state)
        return {"status": "PRIVATE_HOLDOUT_SEALED",
                "manifest_sha256": state["sealed_manifest_sha256"],
                "real_positive_accuracy_certified": False,
                "human_authenticity_certified": False}
    finally:
        lock.unlink(missing_ok=True)


def capture_pending(root: Path, *, seconds: int, consent_attested: bool) -> Path:
    """Opt-in microphone capture. Remains PENDING until human review + import."""
    if consent_attested is not True or not 2 <= seconds <= 8:
        raise ValueError("consent and recording duration 2-8 sec required")
    root = _private_root(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = root / "pending"
    pending.mkdir(mode=0o700, exist_ok=True)
    import pyaudio  # opt-in only: never use microphone during tests/import/summary
    pa = pyaudio.PyAudio()
    stream = None
    output = pending / (secrets.token_hex(16) + ".wav")
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                         input=True, frames_per_buffer=1280)
        frames = [stream.read(1280, exception_on_overflow=False)
                  for _ in range(math.ceil(seconds * 16000 / 1280))]
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"".join(frames))
        _inspect_pcm(output)
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        pa.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description="Private human Hey Jarvis collection")
    parser.add_argument("action", choices=("record", "import", "summary", "seal"))
    parser.add_argument("--root", type=Path, required=True,
                        help="PRIVATE directory OUTSIDE Git checkout")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--speaker-id")
    parser.add_argument("--split", choices=sorted(VALID_SPLITS))
    parser.add_argument("--accent", default="es-CL")
    parser.add_argument("--condition", choices=sorted(VALID_CONDITIONS))
    parser.add_argument("--distance", choices=sorted(VALID_DISTANCES),
                        default="near")
    parser.add_argument("--consent-verified", action="store_true")
    parser.add_argument("--human-confirmed", action="store_true")
    parser.add_argument("--reviewed-exact-phrase", action="store_true")
    parser.add_argument("--seconds", type=int, default=4)
    args = parser.parse_args()
    try:
        if args.action == "record":
            file = capture_pending(args.root, seconds=args.seconds,
                                   consent_attested=args.consent_verified)
            result = {"status": "PENDING_MANUAL_REVIEW", "local_file": str(file),
                      "included_in_corpus": False}
        elif args.action == "import":
            if args.file is None or not args.human_confirmed:
                raise ValueError("WAV file and independently confirmed human voice required")
            result = ingest_wav(
                args.root, args.file, speaker_id=args.speaker_id,
                split=args.split, accent=args.accent,
                condition=args.condition, distance=args.distance,
                consent_attested=args.consent_verified,
                reviewed_exact_phrase=args.reviewed_exact_phrase)
        elif args.action == "summary":
            result = corpus_summary(args.root)
        else:
            result = seal_holdout(args.root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, wave.Error, ImportError) as exc:
        # Never print personal filenames or an audio transcript on failure.
        print(json.dumps({"status": "NOT_CERTIFIED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
