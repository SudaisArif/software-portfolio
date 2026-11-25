"""Portable rendering safeguards; the actual MP4 is also validated by ffprobe."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import wave

HAS_RENDER_DEPS = all(importlib.util.find_spec(module) for module in ("PIL", "numpy"))


@unittest.skipUnless(HAS_RENDER_DEPS, "Install renderer/requirements.txt for render checks")
class RendererTests(unittest.TestCase):
    def test_missing_narration_never_implicitly_invokes_system_voice(self):
        """Every ordinary entry point fails before speech or output side effects."""
        from renderer.render import main
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "review" / "sample.mp4"
            for options in ([], ["--audio-only"], ["--poster-only"], ["--voice", "Daniel"]):
                with self.subTest(options=options), \
                        mock.patch("renderer.render.prepare_audio") as system_voice, \
                        mock.patch("renderer.render.subprocess.run") as subprocess_run, \
                        mock.patch("renderer.render.subprocess.Popen") as subprocess_open, \
                        contextlib.redirect_stderr(io.StringIO()) as error:
                    with self.assertRaises(SystemExit) as blocked:
                        main(["--output", str(output), *options])
                    self.assertEqual(blocked.exception.code, 2)
                    self.assertIn("--system-voice-preview", error.getvalue())
                    system_voice.assert_not_called()
                    subprocess_run.assert_not_called()
                    subprocess_open.assert_not_called()
                    self.assertFalse(output.parent.exists())

    def test_caption_wrapping_preserves_script(self):
        from renderer.render import SEGMENTS, caption_chunks
        for text, _, _ in SEGMENTS:
            lines = caption_chunks(text, 36)
            self.assertEqual(" ".join(lines), text)
            self.assertTrue(all(len(line) <= 36 for line in lines))
            self.assertLessEqual(len(lines), 3, "Captions must fit the shared platform-safe area")

    def test_srt_rounding_carries_seconds(self):
        from renderer.render import srt_time
        self.assertEqual(srt_time(59.9996), "00:01:00,000")

    def test_all_styles_animate_and_are_distinct(self):
        from renderer.render import STYLES, frame
        from PIL import ImageChops
        timeline = [{"index":0,"start":0,"end":10,"text":"Choose the cue.","title":"THE NEXT\nREP","chapter":"01 / REVIEW"}]
        samples = []
        for style in STYLES:
            a, b = frame(1, timeline, 10, style), frame(2, timeline, 10, style)
            self.assertEqual(a.size, (1080, 1920))
            self.assertIsNotNone(ImageChops.difference(a.crop((0,650,1080,1400)), b.crop((0,650,1080,1400))).getbbox())
            samples.append(a)
        for a,b in zip(samples,samples[1:]):
            self.assertIsNotNone(ImageChops.difference(a,b).getbbox())


@unittest.skipUnless(HAS_RENDER_DEPS, "Install renderer/requirements.txt for render checks")
class AlignedNarrationTests(unittest.TestCase):
    segments = [("Move.", "MOVE.", "01 / CUE"), ("Rest.", "REST.", "02 / REST"), ("Repeat.", "REPEAT.", "03 / REPEAT")]

    def alignment(self, text="Move. Rest. Repeat."):
        return {"characters": list(text), "character_start_times_seconds": [i*.075 for i in range(len(text))], "character_end_times_seconds": [(i+1)*.075 for i in range(len(text))]}

    def test_character_alignment_maps_segment_boundaries(self):
        from renderer.render import aligned_timeline
        timeline = aligned_timeline({"alignment": self.alignment()}, self.segments, 2)
        self.assertEqual([entry["text"] for entry in timeline], ["Move.", "Rest.", "Repeat."])
        self.assertEqual(timeline[0]["start"], 0)
        self.assertEqual(timeline[0]["end"], .375)
        self.assertEqual(timeline[1]["start"], .45)
        self.assertEqual(timeline[-1]["end"], 1.425)

    def test_whitespace_is_normalized_without_merging_words(self):
        from renderer.render import aligned_timeline
        timeline = aligned_timeline(self.alignment("Move.\n  Rest.\nRepeat."), self.segments, 3)
        self.assertEqual(timeline[1]["start"], .6)
        for changed in ("move. Rest. Repeat.", "Move.Rest. Repeat.", "Move. Rest. Repeated."):
            with self.subTest(text=changed), self.assertRaisesRegex(ValueError, "does not exactly match"):
                aligned_timeline(self.alignment(changed), self.segments, 3)

    def test_invalid_alignment_timestamps_and_arrays_are_rejected(self):
        from renderer.render import aligned_timeline
        invalid = []
        for value in (float("nan"), float("inf"), -1, True, "0"):
            fixture = self.alignment(); fixture["character_start_times_seconds"][0] = value; invalid.append(fixture)
        backwards = self.alignment(); backwards["character_start_times_seconds"][4] = .1; invalid.append(backwards)
        outside = self.alignment(); outside["character_end_times_seconds"][-1] = 3; invalid.append(outside)
        unequal = self.alignment(); unequal["characters"].pop(); invalid.append(unequal)
        empty = self.alignment(); empty["characters"] = []; invalid.append(empty)
        for fixture in invalid:
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                aligned_timeline(fixture, self.segments, 2)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_prerecorded_audio_render_uses_alignment_without_macos(self):
        """A synthetic tone verifies the audio/align/render path, not speech quality."""
        import numpy as np
        from renderer.render import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            narration, alignment, brief, output = [root / name for name in ("tone.wav", "alignment.json", "brief.json", "test.mp4")]
            samples = (.1 * np.sin(np.arange(16000 * 2) * 2 * np.pi * 220 / 16000) * 32767).astype(np.int16)
            with wave.open(str(narration), "wb") as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(samples.tobytes())
            alignment.write_text(json.dumps(self.alignment()))
            brief.write_text(json.dumps({"title": "Synthetic integration fixture", "segments": [dict(zip(("text", "title", "chapter"), item)) for item in self.segments], "sources": []}))
            with mock.patch("renderer.render.prepare_audio", side_effect=AssertionError("macOS voice must not run")):
                main(["--brief", str(brief), "--narration", str(narration), "--alignment", str(alignment), "--output", str(output), "--style", "editorial", "--preview-seconds", "1"])
            self.assertTrue(output.is_file())
            manifest = json.loads(output.with_suffix(".json").read_text())
            self.assertFalse(manifest["publishable"])
            self.assertEqual(manifest["timeline"][1]["start"], .45)
            voice = next(asset for asset in manifest["assets"] if asset["kind"] == "narration")
            self.assertEqual(voice["rights_status"], "requires_external_license_verification")
            self.assertTrue(json.loads(output.with_suffix(".qc.json").read_text())["passed"])


if __name__ == "__main__":
    unittest.main()
