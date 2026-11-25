"""Reject evidence/timeline loss and changed or undocumented source footage."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch


HAS_RENDER_DEPS = all(importlib.util.find_spec(module) for module in ("PIL", "numpy"))
ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(HAS_RENDER_DEPS, "Install renderer/requirements.txt")
class StudyRendererTests(unittest.TestCase):
    def brief(self):
        return json.loads((ROOT / "renderer/study-brief.json").read_text())

    def test_shipped_brief_preserves_scope_and_readable_text(self):
        from renderer.study import validate_brief, overlay, title_size, wrap, font, SAFE_RIGHT, SAFE_LEFT
        brief = self.brief()
        validate_brief(brief)
        self.assertGreaterEqual(len({beat["shot"] for beat in brief["beats"]}), 3)
        self.assertEqual(brief["narration_mode"], "none_intentional_visual_essay")
        self.assertGreaterEqual(len(brief["sources"]), 2)
        for beat in brief["beats"]:
            size = title_size(beat["title"])
            self.assertTrue(all(font(size, bold=True).getlength(line) <= SAFE_RIGHT - SAFE_LEFT for line in beat["title"]))
            self.assertLessEqual(len(wrap(beat["caption"])), 3)
            self.assertEqual(overlay(beat, beat["start"] + .5, brief["duration_seconds"], next(source for source in brief["sources"] if source["id"] == beat["source"])).size, (1080, 1920))

    def test_discontinuous_nonfinite_and_unattributed_beats_fail(self):
        from renderer.study import validate_brief
        changes = [
            ("start", .1), ("end", float("nan")), ("source_start", -1),
            ("speed", True), ("speed", 0), ("source", "invented-study"),
            ("caption", "too wide " * 30), ("title", ["X" * 100]),
        ]
        for key, value in changes:
            brief = self.brief(); brief["beats"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_brief(brief)
        brief = self.brief(); brief["beats"][-1]["end"] -= .5
        with self.assertRaisesRegex(ValueError, "duration"):
            validate_brief(brief)
        brief = self.brief(); brief["factual_caveat"] = ""
        with self.assertRaisesRegex(ValueError, "caveat"):
            validate_brief(brief)

    def fixture(self, root):
        folder = root / "assets/footage"; folder.mkdir(parents=True)
        media = folder / "test.mp4"; media.write_bytes(b"test footage integrity fixture")
        brief = self.brief()
        for beat in brief["beats"]:
            beat["shot"] = "test"
        provenance = {"assets": [{"id": "test", "local_path": "assets/footage/test.mp4", "sha256": hashlib.sha256(media.read_bytes()).hexdigest(), "license": "Pexels License", "license_url": "https://www.pexels.com/license/"}]}
        return brief, provenance, media

    def test_missing_changed_unlicensed_and_escaping_footage_fails(self):
        from renderer.study import verify_assets
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); brief, provenance, media = self.fixture(root)
            with patch("renderer.study.probe", return_value={"format": {"duration": "20"}}):
                self.assertEqual(set(verify_assets(brief, provenance, root)), {"test"})
                media.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    verify_assets(brief, provenance, root)
                media.unlink()
                with self.assertRaisesRegex(ValueError, "Missing footage"):
                    verify_assets(brief, provenance, root)
                unsafe = copy.deepcopy(provenance); unsafe["assets"][0]["local_path"] = "../outside.mp4"
                with self.assertRaisesRegex(ValueError, "inside assets/footage"):
                    verify_assets(brief, unsafe, root)
                unlicensed = copy.deepcopy(provenance); unlicensed["assets"][0]["license"] = "unknown"
                with self.assertRaisesRegex(ValueError, "license"):
                    verify_assets(brief, unlicensed, root)

    def test_source_interval_cannot_overrun_footage(self):
        from renderer.study import verify_assets
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); brief, provenance, _ = self.fixture(root)
            with patch("renderer.study.probe", return_value={"format": {"duration": "3"}}), self.assertRaisesRegex(ValueError, "exceeds"):
                verify_assets(brief, provenance, root)

    @unittest.skipUnless(shutil.which("ffprobe"), "FFprobe required")
    def test_local_playlist_cannot_open_network_media(self):
        from renderer.study import probe
        with tempfile.TemporaryDirectory() as temp:
            disguised = Path(temp) / "playlist.m3u8"
            disguised.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1:9/blocked.ts\n#EXT-X-ENDLIST\n")
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                probe(disguised)
            self.assertIn(b"not on whitelist", raised.exception.stderr)

    def test_citations_and_design_are_required_per_brief(self):
        from renderer.study import validate_brief
        brief = self.brief(); del brief["sources"][0]["display_citation"]
        with self.assertRaisesRegex(ValueError, "display citation"):
            validate_brief(brief)
        brief = self.brief(); del next(beat for beat in brief["beats"] if beat["layout"] == "design")["design_badges"]
        with self.assertRaisesRegex(ValueError, "design_badges"):
            validate_brief(brief)


@unittest.skipUnless(HAS_RENDER_DEPS, "Install renderer/requirements.txt")
class NarratedStudyTests(unittest.TestCase):
    def aligned_fixture(self, directory):
        path = Path(directory) / "narration.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b"\0\0" * (65 * 8000))
        script = {"script":"One exact sentence.", "segments":[{"id":"s01", "text":"One exact sentence."}]}
        alignment = {"duration_seconds":65, "audio_sha256":hashlib.sha256(path.read_bytes()).hexdigest(), "segments":[{"id":"s01", "text":"One exact sentence.", "start":.1, "end":2.1}]}
        return path, script, alignment

    def test_narration_and_alignment_must_bind_exact_audio_and_script(self):
        from renderer.narrated_study import validate_alignment
        with tempfile.TemporaryDirectory() as directory:
            path, script, alignment = self.aligned_fixture(directory)
            self.assertEqual(validate_alignment(script, alignment, path)[0], 65)
            changed = copy.deepcopy(alignment); changed["audio_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "checksum"):
                validate_alignment(script, changed, path)
            changed = copy.deepcopy(alignment); changed["segments"][0]["text"] = "One invented sentence."
            with self.assertRaisesRegex(ValueError, "exact narration"):
                validate_alignment(script, changed, path)
            changed = copy.deepcopy(alignment); changed["segments"][0]["end"] = 66
            with self.assertRaisesRegex(ValueError, "timings"):
                validate_alignment(script, changed, path)

    def test_word_captions_preserve_exact_text_and_measured_boundaries(self):
        from renderer.narrated_study import validate_alignment, caption_cues
        with tempfile.TemporaryDirectory() as directory:
            path, script, alignment = self.aligned_fixture(directory)
            words = [{"text":"One", "start":.1, "end":.4}, {"text":"exact", "start":.5, "end":1}, {"text":"sentence.", "start":1.2, "end":2.1}]
            alignment["segments"][0]["words"] = words
            _, segments = validate_alignment(script, alignment, path)
            cues = caption_cues(segments)
            self.assertEqual(" ".join(c["text"] for c in cues), script["script"])
            self.assertEqual((cues[0]["start"], cues[0]["end"]), (.1, 2.1))
            alignment["segments"][0]["words"][1]["start"] = .2
            with self.assertRaisesRegex(ValueError, "word alignment"):
                validate_alignment(script, alignment, path)

    def test_editorial_cut_uses_audio_boundaries_without_gaps(self):
        from renderer.narrated_study import build_beats
        script = {"sources":[{"id":"study"}]}
        segments = [{"id":"s01", "start":.1,"end":3.2,"text":"One"},{"id":"s02", "start":3.46,"end":64,"text":"Two"}]
        plans = {"segments":[{"id":"s01","source":"study","title":["One"],"chapter":"STUDY","shots":[{"shot":"a"},{"shot":"b"}]},{"id":"s02","source":"study","title":["Two"],"chapter":"STUDY","shots":[{"shot":"c"}]}]}
        beats, duration = build_beats(script, plans, segments, 65.01)
        self.assertEqual(beats[0]["start"], 0)
        self.assertEqual(beats[-1]["end"], duration)
        self.assertTrue(all(a["end"] == b["start"] for a,b in zip(beats, beats[1:])))
        self.assertTrue(all(abs(b["start"] * 24 - round(b["start"] * 24)) < 1e-8 for b in beats))
        plans["segments"][0]["source"] = "invented"
        with self.assertRaisesRegex(ValueError, "unknown"):
            build_beats(script, plans, segments, 65.01)


if __name__ == "__main__":
    unittest.main()
