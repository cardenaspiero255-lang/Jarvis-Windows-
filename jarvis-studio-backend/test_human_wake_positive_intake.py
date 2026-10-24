"""RED tests for private human 'Hey Jarvis' positive collection, no audio committed."""
import array
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from human_wake_positive_intake import ingest_wav, corpus_summary, seal_holdout


def make_wav(path, *, rate=16000, channels=1, silence=False):
    samples = array.array("h", (0 if silence else int(1800 * math.sin(i / 12))
                                for i in range(rate * 2 * channels)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


class HumanWakePositiveIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.input = make_wav(Path(self.temp.name) / "source.wav")

    def add(self, *, speaker="spkr_0001", split="development",
            condition="quiet", consent=True, reviewed=True,
            source_kind="recorded_human", input_path=None):
        return ingest_wav(
            self.root, input_path or self.input, speaker_id=speaker,
            split=split, accent="es-CL", condition=condition,
            distance="near", consent_attested=consent,
            reviewed_exact_phrase=reviewed, source_kind=source_kind
        )

    def test_a_valid_human_claim_is_private_and_uncertified(self):
        receipt = self.add()
        self.assertEqual(receipt["status"], "PRIVATE_SAMPLE_INGESTED")
        self.assertFalse(receipt["human_authenticity_certified"])
        self.assertFalse(receipt["release_certified"])
        self.assertNotIn("clip_sha256", receipt)
        manifest = self.root / "manifest.private.json"
        data = json.loads(manifest.read_text("utf-8"))
        self.assertEqual(len(data["samples"]), 1)
        self.assertEqual(data["samples"][0]["speaker_id"], "spkr_0001")
        self.assertEqual(data["samples"][0]["phrase"], "hey jarvis")
        self.assertIn("sha256", data["samples"][0])
        self.assertEqual(len(list((self.root / "audio").glob("*.wav"))), 1)

    def test_consent_human_origin_and_phrase_review_mandatory(self):
        for change in (
            {"consent": False}, {"reviewed": False}, {"source_kind": "synthetic"},
            {"speaker": "../real_name"}, {"condition": "other"}
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.add(**change)
        self.assertFalse((self.root / "manifest.private.json").exists())

    def test_silent_non_pcm_and_wrong_sample_rate_rejected(self):
        for kwargs in ({"silence": True}, {"rate": 8000}, {"channels": 2}):
            with self.subTest(kwargs=kwargs):
                path = make_wav(Path(self.temp.name) / "bad.wav", **kwargs)
                with self.assertRaises(ValueError):
                    self.add(input_path=path)
        self.assertFalse((self.root / "manifest.private.json").exists())

    def test_same_audio_and_same_speaker_across_splits_rejected(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add(speaker="spkr_0002")
        path = make_wav(Path(self.temp.name) / "different.wav")
        # Exact same bytes as the first file are a duplicate even if a different path.
        with self.assertRaises(ValueError):
            self.add(speaker="spkr_0002", split="holdout", input_path=path)
        with wave.open(str(path), "rb") as w:
            data = bytearray(w.readframes(w.getnframes()))
        data[100] = (data[100] + 1) % 256
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(data)
        with self.assertRaises(ValueError):
            self.add(speaker="spkr_0001", split="holdout", input_path=path)

    def test_unbalanced_corpus_does_not_pretend_to_measure_recall(self):
        self.add()
        report = corpus_summary(self.root)
        self.assertEqual(report["status"], "NOT_CERTIFIED")
        self.assertEqual(report["clips"], 1)
        self.assertIsNone(report["false_reject_rate"])
        self.assertFalse(report["speaker_independence_certified"])
        self.assertNotIn("spkr_0001", json.dumps(report))
        with self.assertRaises(ValueError):
            seal_holdout(self.root)

    def test_complete_local_split_can_seal_and_cannot_be_mutated(self):
        conditions = ["quiet", "fan", "far_field"]
        for split, prefix in (("development", "d"), ("holdout", "h")):
            for speaker_index in range(3):
                for cond_index, condition in enumerate(conditions):
                    new = Path(self.temp.name) / f"{prefix}{speaker_index}_{cond_index}.wav"
                    make_wav(new)
                    # Different valid PCM bytes for every sample, preserving format.
                    with wave.open(str(new), "rb") as w:
                        pcm = bytearray(w.readframes(w.getnframes()))
                    pcm[200] = (pcm[200] + speaker_index * 9 + cond_index + (0 if prefix == "d" else 27) + 1) % 256
                    with wave.open(str(new), "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                        w.writeframes(pcm)
                    self.add(speaker=f"{prefix}_spk_{speaker_index}",
                             split=split, condition=condition, input_path=new)
        report = corpus_summary(self.root)
        self.assertEqual(report["status"], "PRIVATE_CORPUS_READY_TO_SEAL")
        sealed = seal_holdout(self.root)
        self.assertEqual(sealed["status"], "PRIVATE_HOLDOUT_SEALED")
        self.assertRegex(sealed["manifest_sha256"], r"^[a-f0-9]{64}$")
        with self.assertRaises(ValueError):
            self.add(speaker="spkr_new")
        self.assertEqual(corpus_summary(self.root)["status"], "PRIVATE_HOLDOUT_SEALED")

    def test_symlink_source_rejected(self):
        alias = Path(self.temp.name) / "alias.wav"
        try:
            alias.symlink_to(self.input)
        except OSError:
            self.skipTest("Symlinks unsupported by runner")
        with self.assertRaises(ValueError):
            self.add(input_path=alias)

    def test_private_root_inside_repository_is_rejected(self):
        project = Path(__file__).resolve().parent.parent
        with self.assertRaises(ValueError):
            ingest_wav(project / "private-wake", self.input, speaker_id="spkr_0001",
                       split="development", accent="es-CL", condition="quiet",
                       distance="near", consent_attested=True, reviewed_exact_phrase=True)


if __name__ == "__main__":
    unittest.main()
