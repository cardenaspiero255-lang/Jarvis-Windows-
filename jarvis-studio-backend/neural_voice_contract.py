"""Independent verdict policy for actual Windows Piper/openWakeWord inference."""
import math


def piper_verdict(clips):
    valid = (
        isinstance(clips, list) and len(clips) >= 3
        and all(
            isinstance(c, dict)
            and isinstance(c.get("sample_rate"), int)
            and c["sample_rate"] >= 16000
            and isinstance(c.get("duration_s"), (int, float))
            and 0.45 <= c["duration_s"] <= 45
            and isinstance(c.get("rms"), (int, float))
            and math.isfinite(c["rms"]) and c["rms"] > 180
            and isinstance(c.get("peak"), (int, float))
            and c["peak"] > 500
            and c.get("channels") == 1
            and c.get("sample_width") == 2
            for c in clips
        )
    )
    return "PIPER_SYNTHESIS_PASS" if valid else "NOT_CERTIFIED"


def wake_verdict(positive, negative, silence, threshold):
    if (
        not isinstance(positive, list) or len(positive) < 2
        or not isinstance(negative, list) or len(negative) < 2
        or not isinstance(threshold, (float, int)) or not 0 < threshold < 1
        or not isinstance(silence, (float, int))
    ):
        return "NOT_CERTIFIED"
    scores = positive + negative + [silence]
    if any(not isinstance(s, (int, float)) or
           not math.isfinite(s) or s < 0 or s > 1 for s in scores):
        return "NOT_CERTIFIED"
    if sum(score >= threshold for score in positive) < 1:
        return "NOT_CERTIFIED"
    if any(score >= threshold for score in negative + [silence]):
        return "NOT_CERTIFIED"
    return "WAKE_ACOUSTIC_PASS"
