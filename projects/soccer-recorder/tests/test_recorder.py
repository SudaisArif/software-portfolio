from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from datetime import date, datetime, time, timezone

from soccer_recorder.models import Game, HudlEvent, StreamSnapshot
from soccer_recorder.recorder import GameRecorder, RecorderSettings, is_final_status, safe_filename


class FakeProcess:
    def __init__(self) -> None:
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        self.stopped = True
        return 0

    def kill(self):
        self.stopped = True


class EndingAdapter:
    provider = "hudl"

    def __init__(self, end_status="Archived") -> None:
        self.calls = 0
        self.end_status = end_status

    def snapshot(self, event_id):
        self.calls += 1
        if self.calls == 1:
            return StreamSnapshot(event_id, "Game", datetime.now(timezone.utc), "Streaming", True, "https://stream.test/live.m3u8")
        return StreamSnapshot(
            event_id,
            "Game",
            datetime.now(timezone.utc),
            self.end_status,
            True,
            "https://stream.test/stale.m3u8",
        )


class CapturingNotifier:
    def __init__(self) -> None:
        self.finalizing = 0
        self.completed = 0

    def recording_started(self, game, event):
        pass

    def recording_finalizing(self, game, event):
        self.finalizing += 1

    def recording_completed(self, game, event, output_file):
        self.completed += 1


class RecorderTests(unittest.TestCase):
    def test_safe_filename(self) -> None:
        self.assertEqual(safe_filename("CMU / Men's Soccer vs. Team!"), "CMU-Men-s-Soccer-vs.-Team")

    def test_final_status_normalization(self) -> None:
        self.assertTrue(is_final_status("Archived"))
        self.assertTrue(is_final_status("ADS-POST"))
        self.assertTrue(is_final_status("  COMPLETED  "))
        self.assertFalse(is_final_status("Streaming"))

    def test_archived_status_wins_over_stale_streaming_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = EndingAdapter()
            notifier = CapturingNotifier()
            recorder = object.__new__(GameRecorder)
            recorder.adapter = adapter
            recorder.settings = RecorderSettings(root, poll_seconds=0, monitor_immediately=True)
            recorder.notifier = notifier
            recorder.ffmpeg = "unused"
            recorder.ffprobe = "unused"
            process = FakeProcess()

            def start_ffmpeg(_url, part_path, _log_path):
                part_path.write_bytes(b"captured-video")
                return process

            def finalize(_parts, output_file, _parts_dir, _log_path):
                output_file.write_bytes(b"validated-mp4")

            recorder._start_ffmpeg = start_ffmpeg
            recorder._finalize = finalize
            game = Game(1, date.today(), "Home", "Away", time(19), "https://example.test/?B=1")
            event = HudlEvent("123", "Game", datetime.now(timezone.utc), "Streaming")
            result = recorder.record(game, threading.Event(), resolved_event=event)

            self.assertEqual(result.status, "completed")
            self.assertEqual(adapter.calls, 2)
            self.assertTrue(process.stopped)
            self.assertEqual(notifier.finalizing, 1)
            self.assertEqual(notifier.completed, 1)

    def test_no_new_bytes_ends_a_provider_stuck_on_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = EndingAdapter(end_status="Streaming")
            notifier = CapturingNotifier()
            recorder = object.__new__(GameRecorder)
            recorder.adapter = adapter
            recorder.settings = RecorderSettings(
                root,
                poll_seconds=0,
                monitor_immediately=True,
                stop_grace_seconds=0,
            )
            recorder.notifier = notifier
            recorder.ffmpeg = "unused"
            recorder.ffprobe = "unused"
            process = FakeProcess()

            def start_ffmpeg(_url, part_path, _log_path):
                part_path.write_bytes(b"captured-video")
                return process

            def finalize(_parts, output_file, _parts_dir, _log_path):
                output_file.write_bytes(b"validated-mp4")

            recorder._start_ffmpeg = start_ffmpeg
            recorder._finalize = finalize
            game = Game(1, date.today(), "Home", "Away", time(19), "https://example.test/?B=1")
            event = HudlEvent("123", "Game", datetime.now(timezone.utc), "Streaming")
            result = recorder.record(game, threading.Event(), resolved_event=event)

            self.assertEqual(result.status, "completed")
            self.assertGreaterEqual(adapter.calls, 2)
            self.assertTrue(process.stopped)
            self.assertEqual(notifier.finalizing, 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
    def test_finalizes_transport_stream_parts_to_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts_dir = root / "parts"
            parts_dir.mkdir()
            parts = [parts_dir / "part-001.ts", parts_dir / "part-002.ts"]
            for index, part in enumerate(parts):
                completed = subprocess.run(
                    [
                        shutil.which("ffmpeg"),
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={'blue' if index == 0 else 'red'}:s=320x180:r=15:d=0.5",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=48000:cl=stereo",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-c:a",
                        "aac",
                        "-f",
                        "mpegts",
                        str(part),
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            recorder = object.__new__(GameRecorder)
            recorder.ffmpeg = shutil.which("ffmpeg")
            recorder.ffprobe = shutil.which("ffprobe")
            output = root / "game.mp4"
            recorder._finalize(parts, output, parts_dir, root / "finalize.log")
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)
            self.assertTrue(all(part.exists() for part in parts), "Finalization must retain the raw recordings")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
    def test_creates_checkpoint_without_removing_active_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = root / "active.ts"
            generated = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=green:s=320x180:r=15:d=3",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-f",
                    "mpegts",
                    str(part),
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr.decode(errors="replace"))
            recorder = object.__new__(GameRecorder)
            recorder.ffmpeg = shutil.which("ffmpeg")
            recorder.ffprobe = shutil.which("ffprobe")
            checkpoint = root / "checkpoint.mp4"
            recorder._create_checkpoint(part, checkpoint, root / "checkpoint.log", seconds=2)
            self.assertTrue(checkpoint.exists())
            self.assertTrue(part.exists(), "Creating a checkpoint must not remove or alter the full recording part")


if __name__ == "__main__":
    unittest.main()
