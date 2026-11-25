import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("local_caption_alignment", Path(__file__).resolve().parents[1] / "scripts/align-local-captions.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalCaptionAlignmentTests(unittest.TestCase):
    def fixture(self):
        return ({"audio_sha256": "same", "segments": [{"id": "a", "text": "Twenty-one lifters.", "start": 0, "end": 2}]},
                {"source_sha256": "same", "segments": [{"words": [{"word": "21", "start": 0, "end": 1}, {"word": "lifters.", "start": 1, "end": 2}]}]})

    def test_number_normalization_preserves_script_and_measured_times(self):
        a, r = self.fixture(); result = module.align(a, r)
        self.assertEqual(result["segments"][0]["words"][0], {"text": "Twenty-one", "start": 0, "end": 1, "timing_source": "offline_asr_matched_to_exact_script"})
        self.assertNotIn("words", a["segments"][0])

    def test_other_audio_rejected(self):
        a, r = self.fixture(); r["source_sha256"] = "other"
        with self.assertRaises(ValueError): module.align(a, r)

    def test_missing_or_repeated_speech_rejected(self):
        a, r = self.fixture(); r["segments"][0]["words"].append({"word": "lifters", "start": 2, "end": 3})
        with self.assertRaises(ValueError): module.align(a, r)
        r["segments"][0]["words"] = r["segments"][0]["words"][:1]
        with self.assertRaises(ValueError): module.align(a, r)

    def test_zero_duration_asr_uses_measured_sentence_without_invention(self):
        a, r = self.fixture(); r["segments"][0]["words"][0]["end"] = 0
        result = module.align(a, r)
        self.assertEqual(result["sentence_fallback_segments"], ["a"])
        self.assertNotIn("words", result["segments"][0])

    def test_different_spoken_word_rejected(self):
        a, r = self.fixture(); r["segments"][0]["words"][1]["word"] = "runners"
        with self.assertRaises(ValueError): module.align(a, r)
