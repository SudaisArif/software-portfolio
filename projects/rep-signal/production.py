"""Render an approved script with owner-attested, licensed external narration.

This orchestrator records the owner's rights assertion; a URL is not legal
verification. The result always requires a separate human release decision.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from urllib.parse import urlsplit
import uuid

from media_engine import GateError

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "output/production"
FONT_LICENSE_URL = "https://dejavu-fonts.github.io/License.html"


def _sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _source_urls(records):
    if not isinstance(records, list) or not records:
        raise GateError("A nonempty source record list is required")
    if any(not isinstance(record, dict) or not isinstance(record.get("url"), str) for record in records):
        raise GateError("Every source must have a URL")
    return {record["url"] for record in records}


def _probe_narration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, timeout=30, check=True)
    info = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
        raise GateError("Narration has no audio stream")
    duration = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or not 20 <= duration <= 90:
        raise GateError("Production narration must be 20–90 seconds long")
    return duration


def _stop_process(process):
    """Stop the renderer and its FFmpeg child together, without touching other jobs."""
    if process is None or process.poll() is not None:
        return
    def stop(sig):
        if os.name == "posix" and isinstance(process.pid, int) and process.pid > 1:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    stop(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        stop(signal.SIGKILL)
        process.wait(timeout=5)


def render_approved(engine, job_id, brief_path, narration_path, alignment_path,
                    voice_license_url, style="cinematic", *, license_attestation):
    """Validate, snapshot, lease, render, and QC; never approve or publish.

    `license_attestation` must be an explicit owner statement identifying their
    right to distribute this particular voice/audio. The caller is responsible
    for obtaining that human statement; models must never invent it.
    """
    job = engine.get_job(job_id)
    if job["state"] != "APPROVED" or job["approved_revision"] != job["revision"] or not job["script_approved_by"]:
        raise GateError("The exact script revision must be explicitly approved before production rendering")
    if engine.status()["kill_switch"]:
        raise GateError("Emergency kill switch is on")
    if style not in {"cinematic", "editorial", "storytelling"}:
        raise GateError("Unknown rendering style")
    if not isinstance(license_attestation, str) or not license_attestation.strip():
        raise GateError("An explicit owner license attestation is required; a URL alone is insufficient")
    if len(license_attestation) > 4000:
        raise GateError("License attestation must be at most 4000 characters")
    if not isinstance(voice_license_url, str):
        raise GateError("An HTTPS voice-license evidence URL is required")
    license_url = urlsplit(voice_license_url)
    if license_url.scheme != "https" or not license_url.hostname or license_url.username or license_url.password:
        raise GateError("An HTTPS voice-license evidence URL without embedded credentials is required")
    if not re.fullmatch(r"[0-9a-f]{32}", job["id"]):
        raise GateError("Unsupported job identifier")
    paths = [Path(value).resolve() for value in (brief_path, narration_path, alignment_path)]
    for path, limit in zip(paths, (1_000_000, 100_000_000, 5_000_000)):
        if not path.is_file() or path.stat().st_size > limit:
            raise GateError("An input is missing or exceeds its size limit")
    brief = json.loads(paths[0].read_text())
    if not isinstance(brief, dict) or not isinstance(brief.get("segments"), list) or not 3 <= len(brief["segments"]) <= 30:
        raise GateError("The rendering brief requires 3–30 segments")
    segments = []
    for item in brief["segments"]:
        if not isinstance(item, dict):
            raise GateError("Each segment must be an object")
        values = tuple(item.get(key) for key in ("text", "title", "chapter"))
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise GateError("Each segment requires text, title, and chapter")
        text, title, chapter = values
        if len(text) > 110 or len(title.splitlines()) > 3 or any(len(line) > 12 for line in title.splitlines()) or len(chapter) > 35:
            raise GateError("Segment text exceeds the renderer's caption or heading safe bounds")
        segments.append(values)
    if " ".join(segment[0] for segment in segments) != job["script"]:
        raise GateError("The rendering brief does not exactly match the approved script revision")
    expected_urls = _source_urls(job["sources"])
    if _source_urls(brief.get("sources")) != expected_urls:
        raise GateError("The rendering brief sources differ from the approved job sources")
    for asset in job["assets"]:
        if asset["rights_status"] in {"unknown", "preview_only"}:
            raise GateError("Existing unclear or preview-only assets require a separately reviewed replacement job")
    renderer = ROOT / "renderer/render.py"
    fonts = [ROOT / "assets/fonts" / name for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf")]
    font_license = ROOT / "assets/licenses/DejaVu-LICENSE.txt"
    if not renderer.is_file() or not font_license.is_file() or any(not font.is_file() for font in fonts):
        raise GateError("Renderer source, bundled fonts, or font license is missing")
    # Validate alignment before adding assets, consuming a render slot, or writing output.
    from renderer.render import aligned_timeline
    duration = _probe_narration(paths[1])
    timeline = aligned_timeline(json.loads(paths[2].read_text()), segments, duration)
    input_hashes = [_sha256(path) for path in paths]

    folder = OUTPUT_ROOT / job["id"] / f"revision-{job['revision']}" / uuid.uuid4().hex
    inputs = folder / "inputs"
    inputs.mkdir(parents=True, mode=0o700)
    copied = [inputs / "brief.json", inputs / ("narration" + paths[1].suffix.lower()), inputs / "alignment.json"]
    for source, target, expected in zip(paths, copied, input_hashes):
        shutil.copyfile(source, target)
        if _sha256(target) != expected:
            raise GateError("An input changed during snapshotting; no production render was started")
    attestation = {"evidence_url":voice_license_url, "owner_statement":license_attestation.strip(),
                   "scope":"Owner assertion recorded; legal rights have not been independently verified",
                   "narration_sha256":input_hashes[1], "script_revision":job["revision"]}
    (inputs / "voice-rights.json").write_text(json.dumps(attestation, indent=2))
    # Immutable snapshots tie renderer inputs to the engine's source hashes.
    engine.add_asset(job_id, "visuals", renderer, "original", provenance="Original procedural geometry and motion authored for REP SIGNAL")
    engine.add_asset(job_id, "sound_design", renderer, "original", provenance="Original synthesized sound bed in renderer source")
    engine.add_asset(job_id, "narration", copied[1], "licensed", license_url=voice_license_url,
                     provenance="Owner-attested distribution rights: " + license_attestation.strip())
    engine.add_asset(job_id, "alignment", copied[2], "original", provenance="Provider timing data for the owner-supplied narration; text matched to approved script")
    for font in fonts:
        engine.add_asset(job_id, "font", font, "licensed", license_url=FONT_LICENSE_URL,
                         provenance="Bundled DejaVu font with Bitstream Vera/DejaVu permission; assets/licenses/DejaVu-LICENSE.txt")
    attempt = engine.start_render(job_id)
    token = attempt["render_token"]
    video = folder / "film.mp4"
    process = None
    try:
        if attempt["revision"] != job["revision"] or attempt["script"] != job["script"]:
            raise GateError("The script changed during setup; this attempt cannot render")
        command = [sys.executable, str(renderer), "--brief", str(copied[0]), "--narration", str(copied[1]),
                   "--alignment", str(copied[2]), "--style", style, "--output", str(video)]
        with (folder / "render.log").open("w") as log:
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=log, stderr=log, start_new_session=True)
            while True:
                # Heartbeat checks kill switch, cancellation, and the attempt's token.
                engine.render_heartbeat(job_id, render_token=token)
                try:
                    returncode = process.wait(timeout=15)
                    break
                except subprocess.TimeoutExpired:
                    continue
        engine.render_heartbeat(job_id, render_token=token)
        if returncode != 0:
            raise RuntimeError(f"Renderer failed with exit code {returncode}; inspect {folder / 'render.log'}")
        manifest = json.loads(video.with_suffix(".json").read_text())
        if manifest.get("script") != job["script"] or _source_urls(manifest.get("sources")) != expected_urls:
            raise GateError("Rendered manifest differs from the approved script or sources")
        if manifest.get("timeline") != timeline:
            raise GateError("Rendered captions differ from the validated narration alignment")
        voice_asset = next((asset for asset in manifest.get("assets", []) if asset.get("kind") == "narration"), {})
        if voice_asset.get("source_sha256") != input_hashes[1] or voice_asset.get("alignment_sha256") != input_hashes[2]:
            raise GateError("Rendered narration provenance differs from the registered inputs")
        engine.finish_render(job_id, video, manifest["timeline"], revision=attempt["revision"], render_token=token)
        qc = engine.run_qc(job_id)
        return {"job":engine.get_job(job_id), "qc":qc, "output":str(video),
                "awaiting_release_review":bool(qc["passed"]), "publishable":False,
                "license_evidence_scope":attestation["scope"]}
    except BaseException:
        _stop_process(process)
        current = engine.get_job(job_id)
        if current["state"] == "RENDERING" and current.get("render_token") == token:
            engine.fail_render(job_id, retryable=False, render_token=token)
        raise
