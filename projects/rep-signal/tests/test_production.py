"""Approved-render orchestration contract; subprocess output is explicitly simulated."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from media_engine import Engine, GateError
import production


HAS_RENDER_DEPS = all(importlib.util.find_spec(module) for module in ("PIL", "numpy"))


@unittest.skipUnless(HAS_RENDER_DEPS, "Install renderer/requirements.txt for production orchestration tests")
class ApprovedRenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.engine = Engine(self.path / "test.sqlite")
        self.brief = {"title":"Fixture", "sources":[{"url":"https://example.test/research"}],
                      "segments":[{"text":text,"title":text.upper(),"chapter":"01 / TEST"} for text in ("Move.", "Rest.", "Repeat.")]}
        self.script = " ".join(segment["text"] for segment in self.brief["segments"])
        self.alignment = {"characters":list(self.script),
                          "character_start_times_seconds":[i*.1 for i in range(len(self.script))],
                          "character_end_times_seconds":[(i+1)*.1 for i in range(len(self.script))]}
        self.brief_path = self.path / "brief.json"
        self.brief_path.write_text(json.dumps(self.brief))
        self.narration = self.path / "narration.wav"
        self.narration.write_bytes(b"explicit mock narration fixture")
        self.alignment_path = self.path / "alignment.json"
        self.alignment_path.write_text(json.dumps(self.alignment))
        self.job = self.engine.create_job("Fixture")
        self.engine.set_research(self.job["id"], self.brief["sources"], "Synthetic test only")
        self.job = self.engine.set_script(self.job["id"], self.script)
        self.addCleanup(patch.stopall)
        patch("production.OUTPUT_ROOT", self.path / "renders").start()
        patch("production._probe_narration", return_value=20.25).start()

    def approve_fixture(self):
        self.engine.review_script(self.job["id"], "approve", actor="isolated-test-reviewer", revision=self.job["revision"])

    def render(self, **overrides):
        args = {"voice_license_url":"https://example.test/fixture-license",
                "license_attestation":"TEST ONLY: fixture media has no commercial voice or distribution use"}
        args.update(overrides)
        return production.render_approved(self.engine, self.job["id"], self.brief_path,
                                          self.narration, self.alignment_path, **args)

    def assert_no_render_mutation(self, events_before):
        job = self.engine.get_job(self.job["id"])
        self.assertEqual(job["assets"], [])
        self.assertEqual(len(self.engine.audit_log()), events_before)
        self.assertFalse((self.path / "renders").exists())

    def test_unapproved_script_is_blocked_before_file_or_state_changes(self):
        before = len(self.engine.audit_log())
        with patch("production.subprocess.Popen") as popen, self.assertRaisesRegex(GateError, "explicitly approved"):
            self.render()
        popen.assert_not_called()
        self.assert_no_render_mutation(before)

    def test_exact_script_mismatch_is_blocked_before_mutation(self):
        self.approve_fixture()
        self.brief["segments"][0]["text"] = "Move!"
        self.brief_path.write_text(json.dumps(self.brief))
        before = len(self.engine.audit_log())
        with self.assertRaisesRegex(GateError, "exactly match"):
            self.render()
        self.assert_no_render_mutation(before)

    def test_changed_research_source_is_blocked_before_mutation(self):
        self.approve_fixture()
        self.brief["sources"] = [{"url":"https://example.test/unapproved-source"}]
        self.brief_path.write_text(json.dumps(self.brief))
        before = len(self.engine.audit_log())
        with self.assertRaisesRegex(GateError, "sources differ"):
            self.render()
        self.assert_no_render_mutation(before)

    def test_license_url_alone_is_not_an_attestation(self):
        self.approve_fixture()
        before = len(self.engine.audit_log())
        for assertion in ("", "  ", None):
            with self.subTest(assertion=assertion), self.assertRaisesRegex(GateError, "owner license attestation"):
                self.render(license_attestation=assertion)
        with self.assertRaisesRegex(GateError, "HTTPS"):
            self.render(voice_license_url="http://example.test/license")
        self.assert_no_render_mutation(before)

    def fake_process(self, command, on_first_wait=None):
        from renderer.render import aligned_timeline
        output = Path(command[command.index("--output")+1])
        brief_path = Path(command[command.index("--brief")+1])
        audio = Path(command[command.index("--narration")+1])
        alignment = Path(command[command.index("--alignment")+1])
        brief = json.loads(brief_path.read_text())
        segments = [tuple(segment[k] for k in ("text","title","chapter")) for segment in brief["segments"]]
        output.write_bytes(b"explicit fake container; physical QC separately covered by test_e2e.py")
        output.with_suffix(".json").write_text(json.dumps({
            "script":" ".join(segment[0] for segment in segments), "sources":brief["sources"],
            "timeline":aligned_timeline(json.loads(alignment.read_text()), segments, 20.25),
            "assets":[{"kind":"narration", "source_sha256":production._sha256(audio),
                       "alignment_sha256":production._sha256(alignment)}]}))
        class FakeProcess:
            pid = None
            returncode = None
            waits = 0
            terminated = False
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1 and on_first_wait:
                    on_first_wait()
                    raise subprocess.TimeoutExpired(command, timeout)
                self.returncode = -15 if self.terminated else 0
                return self.returncode
            def poll(self):
                return self.returncode
            def terminate(self):
                self.terminated = True
            def kill(self):
                self.terminated = True
        return FakeProcess()

    def test_render_registers_immutable_inputs_and_stops_at_release_review(self):
        self.approve_fixture()
        with patch("production.subprocess.Popen", side_effect=lambda command,**kwargs:self.fake_process(command)) as popen, \
             patch("media_engine.qc.inspect_media", return_value={"checks":dict.fromkeys(["video","audio","duration","resolution","captions"],True)}):
            result = self.render(style="editorial")
        self.assertTrue(result["awaiting_release_review"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result["job"]["state"], "QC")
        self.assertIsNone(result["job"]["release_sha256"])
        self.assertIsNone(result["job"]["release_approved_by"])
        self.assertFalse(popen.call_args.kwargs.get("shell", False))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        voice = next(asset for asset in result["job"]["assets"] if asset["kind"] == "narration")
        self.assertEqual(voice["rights_status"], "licensed")
        self.assertNotEqual(voice["path"], str(self.narration))
        self.narration.write_bytes(b"changed original after snapshot")
        self.assertEqual(production._sha256(voice["path"]), voice["sha256"])

    def test_emergency_stop_terminates_render_without_release(self):
        self.approve_fixture()
        processes = []
        def launch(command, **kwargs):
            process = self.fake_process(command, on_first_wait=lambda:self.engine.kill_switch(True))
            processes.append(process)
            return process
        with patch("production.subprocess.Popen", side_effect=launch), self.assertRaisesRegex(GateError, "kill switch"):
            self.render()
        self.assertTrue(processes[0].terminated)
        job = self.engine.get_job(self.job["id"])
        self.assertEqual(job["state"], "FAILED")
        self.assertIsNone(job["release_sha256"])

    def test_cancellation_remains_cancelled_after_renderer_shutdown(self):
        self.approve_fixture()
        processes = []
        def launch(command, **kwargs):
            process = self.fake_process(command, on_first_wait=lambda:self.engine.cancel(self.job["id"], actor="test-reviewer"))
            processes.append(process)
            return process
        with patch("production.subprocess.Popen", side_effect=launch), self.assertRaisesRegex(GateError, "not rendering"):
            self.render()
        self.assertTrue(processes[0].terminated)
        self.assertEqual(self.engine.get_job(self.job["id"])["state"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
