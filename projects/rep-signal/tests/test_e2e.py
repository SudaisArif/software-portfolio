"""Real-media integration checks. No user job is approved and no API is called.

The production-shaped flow uses its own synthetic media and a temporary database.
The actual sample is only inspected, and its preview-only voice is tested as blocked.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from media_engine import Engine, GateError
from media_engine.qc import inspect_media


ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(HAS_FFMPEG, "Install FFmpeg/ffprobe for real-media integration checks")
class LocalSampleChecks(unittest.TestCase):
    def test_actual_sample_has_measured_platform_format_and_timed_captions(self):
        path = ROOT / "output/sample.mp4"
        manifest_path = path.with_suffix(".json")
        if not path.exists() or not manifest_path.exists():
            self.skipTest("Render the explicitly unapproved local sample first")
        manifest = json.loads(manifest_path.read_text())
        report = inspect_media(path, manifest["timeline"])
        self.assertFalse(manifest["publishable"])
        self.assertFalse(manifest["human_approved"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(all(report["checks"].values()), report)
        self.assertAlmostEqual(report["measurements"]["duration_seconds"], manifest["duration_seconds"], delta=0.1)

    def test_preview_voice_cannot_enter_production_even_with_script_test_approval(self):
        path = ROOT / "output/sample.mp4"
        manifest_path = path.with_suffix(".json")
        if not path.exists() or not manifest_path.exists():
            self.skipTest("Render the explicitly unapproved local sample first")
        manifest = json.loads(manifest_path.read_text())
        voice = next(asset for asset in manifest["assets"] if asset["kind"] == "narration")
        self.assertIn("preview", voice["rights_status"])
        with tempfile.TemporaryDirectory() as temporary:
            engine = Engine(Path(temporary) / "isolated-test.sqlite")
            job = engine.create_job("TEST ONLY: preview rights failure")
            engine.set_research(job["id"], manifest["sources"], "Test of rights refusal; not an approval of the real sample")
            job = engine.set_script(job["id"], manifest["script"])
            engine.review_script(job["id"], "approve", actor="isolated-test-fixture", revision=job["revision"])
            engine.add_asset(job["id"], "visuals", ROOT / "renderer/render.py", "original", provenance="Original procedural renderer source")
            engine.add_asset(job["id"], "sound_design", ROOT / "renderer/render.py", "original", provenance="Original synthesizer source")
            engine.add_asset(job["id"], "font", ROOT / "assets/fonts/DejaVuSans.ttf", "licensed",
                             license_url="https://dejavu-fonts.github.io/License.html", provenance="Bundled DejaVu license")
            engine.add_asset(job["id"], "narration", path, "preview_only", provenance=voice["origin"])
            with self.assertRaisesRegex(GateError, "Unclear asset rights: narration"):
                engine.start_render(job["id"])
            with self.assertRaises(GateError):
                engine.schedule(job["id"], "2026-11-14T18:00:00-05:00", ["youtube"])
            self.assertEqual(engine.get_job(job["id"])["state"], "APPROVED")
            self.assertEqual(engine.get_job(job["id"])["deliveries"], [])


@unittest.skipUnless(HAS_FFMPEG, "Install FFmpeg/ffprobe for real-media integration checks")
class SyntheticEndToEnd(unittest.TestCase):
    """This intentionally uses a test pattern/tone, never preview audio or live APIs."""
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name)
        cls.video = cls.path / "synthetic-test-fixture.mp4"
        # FFmpeg generates all frames and audio here. No stock or user media is used.
        cls.command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=24:duration=20.25",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=20.25",
            "-af", "volume=0.4", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
            "-movflags", "+faststart", "-shortest", str(cls.video),
        ]
        try:
            subprocess.run(cls.command, capture_output=True, check=True, timeout=90)
        except BaseException:
            cls.temporary.cleanup()
            raise
        cls.provenance = cls.path / "fixture-source.json"
        cls.provenance.write_text(json.dumps({"purpose":"synthetic test fixture only", "command":cls.command}))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_real_qc_dry_run_async_receipt_verified_publication_and_metrics(self):
        now = 1805126400.0
        engine = Engine(self.path / "flow.sqlite", clock=lambda: now)
        job = engine.create_job("TEST ONLY: synthetic fixture")
        engine.set_research(job["id"], [{"url":"https://example.test/fixture", "title":"Synthetic test evidence"}], "No real content claim or external action")
        job = engine.set_script(job["id"], "Synthetic fixture for validation of the pipeline state machine.")
        engine.review_script(job["id"], "approve", revision=job["revision"], actor="test-reviewer")
        for kind in ("visuals", "narration", "sound_design"):
            engine.add_asset(job["id"], kind, self.provenance, "original", provenance="Generated test-pattern video and sine signal; this is not a releasable film")
        engine.add_asset(job["id"], "font", ROOT / "assets/fonts/DejaVuSans.ttf", "licensed",
                         license_url="https://dejavu-fonts.github.io/License.html", provenance="Bundled DejaVu test layout font")
        rendering = engine.start_render(job["id"])
        captions = [{"start":0.5, "end":19.5, "text":"SYNTHETIC INTEGRATION TEST"}]
        job = engine.finish_render(job["id"], self.video, captions, revision=rendering["revision"], render_token=rendering["render_token"])
        report = engine.run_qc(job["id"])
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["inspector"], "ffprobe+ffmpeg/v1")
        self.assertTrue(report["checks"]["rights"])
        self.assertEqual(report["measurements"]["width"], 1080)
        engine.approve_release(job["id"], actor="test-reviewer", artifact_sha256=job["artifact_sha256"])
        engine.schedule(job["id"], now, ["youtube"])

        class MockAsyncPublisher:
            account_id = "fixture-channel"
            submissions = 0
            verified = False
            def publish(self, incoming_job, idempotency_key):
                self.submissions += 1
                return {"status":"SUBMITTED", "external_id":"fixture-receipt", "verified":False}
            def verify(self, receipt):
                return {"external_id":receipt, "verified":self.verified,
                        "url":"https://example.test/synthetic-only" if self.verified else None}

        publisher = MockAsyncPublisher()
        self.assertEqual(engine.publish_due({"youtube":publisher})[0]["status"], "DRY_RUN")
        self.assertEqual(publisher.submissions, 0)
        engine.configure_publication(True, {"youtube":"fixture-channel"}, actor="test-reviewer")
        self.assertEqual(engine.publish_due({"youtube":publisher}, dry_run=False)[0]["status"], "SUBMITTED")
        self.assertEqual(engine.reconcile_submissions({"youtube":publisher})[0]["status"], "SUBMITTED")
        self.assertNotEqual(engine.get_job(job["id"])["state"], "PUBLISHED")
        self.assertEqual(engine.publish_due({"youtube":publisher}, dry_run=False), [])
        with self.assertRaises(GateError):
            engine.record_metrics(job["id"], "youtube", {"views":7}, "https://example.test/fixture-analytics")
        publisher.verified = True
        self.assertEqual(engine.reconcile_submissions({"youtube":publisher})[0]["status"], "PUBLISHED")
        self.assertEqual(publisher.submissions, 1)
        engine.record_metrics(job["id"], "youtube", {"views":7, "retention_rate":None}, "https://example.test/fixture-analytics")
        self.assertEqual(engine.get_job(job["id"])["state"], "ANALYZED")
        self.assertEqual(engine.metrics_report()[0]["values"], {"views":7,"retention_rate":None})
        self.assertEqual(engine.status()["costs"]["spent_usd"], 0)
        self.assertEqual(engine.status()["costs"]["reserved_usd"], 0)


if __name__ == "__main__":
    unittest.main()
