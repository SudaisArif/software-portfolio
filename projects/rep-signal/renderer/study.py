#!/usr/bin/env python3
"""Render a licensed real-footage study essay with optional supplied narration.

Downloaded footage is intentionally outside Git. Verify/download the exact media
listed in assets/footage/provenance.json before rendering. All assets are hashed.
The output remains a local review draft regardless of successful technical QC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

if __package__:
    from .render import ROOT, W, H, FPS, SR, font, qc_video, run, srt_time
else:
    from render import ROOT, W, H, FPS, SR, font, qc_video, run, srt_time

CHALK = (241, 237, 228)
COPPER = (226, 143, 101)
MUTED = (190, 199, 190)
SAFE_LEFT, SAFE_RIGHT = 84, 925
SOURCE_INPUT_LIMITS = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,avi,mpegts,ogg"]


def probe(path: Path) -> dict:
    """Local media only: do not let disguised playlists resolve network URLs."""
    return json.loads(run(["ffprobe", "-v", "error", *SOURCE_INPUT_LIMITS, "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def validate_brief(brief: dict) -> None:
    """Fail early on discontinuities, lost citations, or text too large for frame."""
    if not isinstance(brief, dict) or not isinstance(brief.get("beats"), list):
        raise ValueError("Brief requires beats")
    duration = brief.get("duration_seconds")
    if not finite(duration) or not 20 <= duration <= 45:
        raise ValueError("Study essay must last 20–45 seconds")
    sources = {source["id"] for source in brief.get("sources", []) if isinstance(source, dict) and source.get("url", "").startswith("https://")}
    if not sources or not brief.get("factual_caveat"):
        raise ValueError("Evidence URLs and factual caveat are required")
    for source in brief["sources"]:
        if not all(isinstance(source.get(key), str) and source[key].strip() for key in ("display_citation", "doi")):
            raise ValueError("Every source requires its own display citation and DOI")
        if font(25).getlength(source["display_citation"]) > SAFE_RIGHT - SAFE_LEFT or font(21, mono=True).getlength("doi:" + source["doi"]) > SAFE_RIGHT - SAFE_LEFT:
            raise ValueError("Source citation is wider than the portrait safe area")
    if brief.get("narration_mode") != "none_intentional_visual_essay":
        raise ValueError("This renderer produces the intentional voice-free format only")
    previous = 0
    for beat in brief["beats"]:
        values = [beat.get(key) for key in ("start", "end", "source_start", "speed")]
        if not all(finite(value) for value in values):
            raise ValueError("Beat times and playback speed must be finite")
        start, end, source_start, speed = values
        if abs(start - previous) > 1e-6 or end <= start or source_start < 0 or not .5 <= speed <= 1.5:
            raise ValueError("Beats must be contiguous, positive, and use a valid source interval")
        if any(abs(time * FPS - round(time * FPS)) > 1e-6 for time in (start, end)):
            raise ValueError("Beat boundaries must land on video frames")
        if beat.get("source") not in sources or not beat.get("shot"):
            raise ValueError("Every beat needs a known study and footage asset")
        title, caption = beat.get("title"), beat.get("caption")
        if not isinstance(title, list) or not 1 <= len(title) <= 3 or any(not isinstance(line, str) or not line.strip() for line in title):
            raise ValueError("Title requires one to three nonempty lines")
        if not isinstance(caption, str) or not caption.strip() or len(caption.splitlines()) > 3:
            raise ValueError("Caption requires one to three lines")
        if not isinstance(beat.get("chapter"), str) or len(beat["chapter"]) > 30:
            raise ValueError("Chapter must be a short string")
        if any(font(38).getlength(line) > SAFE_RIGHT - SAFE_LEFT for line in caption.splitlines()):
            raise ValueError("Caption is wider than the portrait safe area")
        if any(font(56, bold=True).getlength(line) > SAFE_RIGHT - SAFE_LEFT for line in title):
            raise ValueError("Title cannot fit at the minimum legible size")
        for key, width, size in (("design_badges", 286, 25), ("comparison_badges", 317, 31)):
            if beat.get("layout") == {"design_badges": "design", "comparison_badges": "comparison"}[key]:
                labels = beat.get(key)
                if not isinstance(labels, list) or len(labels) != 2 or any(not isinstance(label, str) or not label.strip() or font(size, mono=True).getlength(label) > width for label in labels):
                    raise ValueError(f"The {beat['layout']} layout requires two readable {key}")
        previous = end
    if abs(previous - duration) > 1e-6:
        raise ValueError("Final beat does not match duration")


def verify_assets(brief: dict, provenance: dict, root: Path = ROOT) -> dict:
    assets = {asset["id"]: asset for asset in provenance.get("assets", [])}
    verified = {}
    for key in {beat["shot"] for beat in brief["beats"]}:
        item = assets.get(key)
        if not item or item.get("license") != "Pexels License" or not item.get("license_url", "").startswith("https://www.pexels.com/"):
            raise ValueError(f"Missing documented footage license: {key}")
        relative = Path(item.get("local_path", ""))
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root.resolve() / "assets/footage"):
            raise ValueError("Footage paths must remain inside assets/footage")
        if not path.is_file():
            raise ValueError(f"Missing footage {relative}; download the provenance media_url")
        if sha256(path) != item.get("sha256"):
            raise ValueError(f"Footage checksum changed: {relative}")
        duration = float(probe(path)["format"]["duration"])
        for beat in [beat for beat in brief["beats"] if beat["shot"] == key]:
            if beat["source_start"] + (beat["end"] - beat["start"]) * beat["speed"] > duration + .001:
                raise ValueError(f"Source interval exceeds available footage: {key}")
        verified[key] = {**item, "path": path, "duration_seconds": duration}
    return verified


def title_size(lines):
    for size in range(114, 55, -2):
        if all(font(size, bold=True).getlength(line) <= SAFE_RIGHT - SAFE_LEFT for line in lines):
            return size
    raise ValueError("Title cannot fit")


def wrap(text, size=38, width=SAFE_RIGHT - SAFE_LEFT):
    lines = []
    for original in text.splitlines():
        current = ""
        for word in original.split():
            candidate = f"{current} {word}".strip()
            if current and font(size).getlength(candidate) > width:
                lines.append(current); current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def shade() -> Image.Image:
    # Face and lifting motion remain visible in the center. Only the typography
    # areas receive heavy contrast treatment, never an opaque full-frame card.
    y = np.arange(H, dtype=np.float32)
    top = np.clip((760 - y) / 520, 0, 1) * 185
    bottom = np.clip((y - 1000) / 460, 0, 1) * 225
    opacity = np.maximum(np.maximum(top, bottom), 12).astype(np.uint8)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[:, :, :3] = (8, 14, 14)
    rgba[:, :, 3] = opacity[:, None]
    return Image.fromarray(rgba)


SHADE = None


def overlay(beat: dict, t: float, duration: float, source_info: dict) -> Image.Image:
    global SHADE
    if SHADE is None:
        SHADE = shade()
    layer = SHADE.copy()
    draw = ImageDraw.Draw(layer)
    elapsed = t - beat["start"]
    reveal = min(1, max(0, elapsed / .18))
    rise = round((1 - reveal) ** 2 * 22)
    draw.rectangle((84, 105, 90, 141), fill=COPPER)
    draw.text((107, 102), "REP SIGNAL", font=font(27, mono=True), fill=CHALK)
    draw.text((84, 183), beat["chapter"], font=font(24, mono=True), fill=MUTED)
    size = title_size(beat["title"])
    for index, line in enumerate(beat["title"]):
        color = COPPER if index == beat.get("accent_line") else CHALK
        draw.text((78, 253 + rise + index * (size + 10)), line, font=font(size, bold=True), fill=color)
    if beat["layout"] == "design":
        # Design metadata is present during the study introduction, not buried
        # only in a caption outside the video.
        for x, label in zip((84, 452), beat["design_badges"]):
            draw.rounded_rectangle((x, 590, x + 324, 656), radius=9, fill=(18, 27, 27, 225), outline=(96, 116, 108, 255), width=1)
            draw.text((x + 19, 608), label, font=font(25, mono=True), fill=CHALK)
    if beat["layout"] == "comparison":
        # Equal-size boxes compare protocols, not invented outcomes/effect sizes.
        for x, label in zip((84, 490), beat["comparison_badges"]):
            draw.rounded_rectangle((x, 595, x + 365, 682), radius=12, fill=(14, 25, 24, 230), outline=COPPER, width=2)
            draw.text((x + 24, 622), label, font=font(31, mono=True), fill=CHALK)
    draw.rectangle((84, 1365, 174, 1371), fill=COPPER)
    for index, line in enumerate(wrap(beat["caption"])):
        draw.text((84, 1404 + index * 57), line, font=font(38), fill=CHALK)
    draw.text((84, 1610), source_info["display_citation"], font=font(25), fill=MUTED)
    draw.text((84, 1647), "doi:" + source_info["doi"], font=font(21, mono=True), fill=MUTED)
    draw.text((84, 1700), "Stock footage · not study participants", font=font(23), fill=MUTED)
    draw.text((84, 1740), "LOCAL REVIEW  /  VOICE-FREE CUT", font=font(20, mono=True), fill=MUTED)
    draw.rectangle((84, 1800, 925, 1804), fill=(67, 82, 76))
    draw.rectangle((84, 1800, 84 + round(841 * t / duration), 1804), fill=COPPER)
    return layer


def soundbed(path: Path, brief: dict) -> None:
    """Original restrained percussion and warm tonal texture, no borrowed music."""
    count = round(brief["duration_seconds"] * SR)
    t = np.arange(count, dtype=np.float32) / SR
    rng = np.random.default_rng(42)
    mono = (.015 * np.sin(2 * np.pi * 110 * t) + .009 * np.sin(2 * np.pi * 164.8138 * t))
    mono *= .65 + .35 * np.sin(2 * np.pi * .1 * t) ** 2
    # Slow heartbeat-like kicks and short texture clicks avoid a mechanical
    # countdown that could be confused with an actual prescribed rest timer.
    for index, at in enumerate(np.arange(.1, brief["duration_seconds"], .625)):
        start = round(at * SR)
        length = min(round(.23 * SR), count - start)
        phase_t = np.arange(length) / SR
        kick = .18 * np.sin(2 * np.pi * (48 * phase_t + 2.8 * (1 - np.exp(-phase_t * 28)))) * np.exp(-phase_t * 23)
        if index % 2:
            kick *= .43
        mono[start:start + length] += kick
        click_start = start + round(.31 * SR)
        click_n = min(round(.045 * SR), count - click_start)
        if click_n > 0:
            noise = rng.normal(0, 1, click_n)
            noise[1:] -= noise[:-1] * .7
            mono[click_start:click_start + click_n] += (.012 * noise * np.exp(-np.arange(click_n) / (SR * .009)))
    for beat in brief["beats"][1:]:
        end = round(beat["start"] * SR)
        length = min(round(.12 * SR), end)
        noise = rng.normal(0, 1, length)
        noise = np.convolve(noise, np.ones(20) / 20, mode="same")
        mono[end-length:end] += .03 * noise * np.linspace(0, 1, length) ** 2
    fade = np.minimum(np.clip(t / .1, 0, 1), np.clip((brief["duration_seconds"] - t) / .65, 0, 1))
    stereo = np.stack([mono * fade, mono * fade], axis=1)
    samples = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(SR); audio.writeframes(samples.tobytes())


def decode_frames(asset: dict, beat: dict):
    seconds = beat["end"] - beat["start"]
    count = round(seconds * FPS)
    vf = f"setpts=(PTS-STARTPTS)/{beat['speed']},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    command = ["ffmpeg", "-v", "error", *SOURCE_INPUT_LIMITS, "-ss", str(beat["source_start"]), "-i", str(asset["path"]), "-an", "-vf", vf, "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    decoder = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(count):
            raw = decoder.stdout.read(W * H * 3)
            if len(raw) != W * H * 3:
                raise RuntimeError("Footage ended before the planned shot boundary")
            yield Image.frombytes("RGB", (W, H), raw)
    finally:
        decoder.stdout.close()
        error = decoder.stderr.read().decode()
        decoder.stderr.close()
        status = decoder.wait()
        if status:
            raise RuntimeError(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, default=ROOT / "renderer/study-brief.json")
    parser.add_argument("--provenance", type=Path, default=ROOT / "assets/footage/provenance.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/study-sample.mp4")
    parser.add_argument("--narration", type=Path, help="Locally generated/recorded licensed PCM WAV; never generates speech")
    parser.add_argument("--alignment", type=Path, help="Exact sentence/word timings for the supplied WAV")
    parser.add_argument("--voice-provenance", type=Path, help="License and voice/model provenance JSON")
    parser.add_argument("--edit", type=Path, help="Narrated editorial shot plan")
    args = parser.parse_args(argv)
    if any((args.narration, args.alignment, args.voice_provenance, args.edit)):
        if not all((args.narration, args.alignment, args.voice_provenance, args.edit)):
            parser.error("Narration requires --narration, --alignment, --voice-provenance and --edit together")
        if __package__:
            from .narrated_study import render_narrated
        else:
            from narrated_study import render_narrated
        return render_narrated(args)
    brief_bytes = args.brief.read_bytes()
    brief = json.loads(brief_bytes)
    validate_brief(brief)
    provenance_bytes = args.provenance.read_bytes()
    provenance = json.loads(provenance_bytes)
    assets = verify_assets(brief, provenance)
    output = args.output.resolve(); output.parent.mkdir(exist_ok=True, parents=True)
    work = output.parent / ("." + output.stem + "-cache"); work.mkdir(exist_ok=True)
    sources_by_id = {source["id"]: source for source in brief["sources"]}
    raw_audio, audio = work / "original-soundbed.wav", work / "normalized-soundbed.wav"
    soundbed(raw_audio, brief)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(raw_audio), "-af", "loudnorm=I=-16:TP=-1.5:LRA=9", "-ar", str(SR), str(audio)])
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(audio), "-t", str(brief["duration_seconds"]), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(output)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for beat in brief["beats"]:
            for index, frame in enumerate(decode_frames(assets[beat["shot"]], beat)):
                t = beat["start"] + index / FPS
                frame = Image.alpha_composite(frame.convert("RGBA"), overlay(beat, t, brief["duration_seconds"], sources_by_id[beat["source"]])).convert("RGB")
                encoder.stdin.write(frame.tobytes())
            print(f"Rendered {beat['end']:g}/{brief['duration_seconds']}s", file=sys.stderr, flush=True)
    finally:
        encoder.stdin.close()
    error = encoder.stderr.read().decode(); encoder.stderr.close()
    if encoder.wait():
        raise RuntimeError(error)
    for asset in assets.values():
        if sha256(asset["path"]) != asset["sha256"]:
            output.unlink(missing_ok=True)
            raise ValueError("Source footage changed during rendering; draft discarded")
    # SRT is a full text transcript for this voice-free visual essay, not a claim
    # of speech alignment. It includes title + explanatory text on each beat.
    output.with_suffix(".srt").write_text("\n\n".join(f"{index+1}\n{srt_time(beat['start'])} --> {srt_time(beat['end'])}\n{' '.join(beat['title'])}\n{beat['caption']}" for index, beat in enumerate(brief["beats"])) + "\n")
    output.with_suffix(".recording.txt").write_text(brief["human_recording_script"] + "\n\n" + brief["human_delivery_direction"] + "\n")
    manifest = {**brief, "script": " ".join(" ".join(beat["title"]) + " " + beat["caption"].replace("\n", " ") for beat in brief["beats"]), "script_kind": "on_screen_visual_essay_text_not_spoken", "status": "LOCAL_REVIEW_SAMPLE", "human_approved": False, "publishable": False, "dimensions": [W, H], "fps": FPS, "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(), "provenance_sha256": hashlib.sha256(provenance_bytes).hexdigest(), "assets": [{key: value for key, value in asset.items() if key != "path"} for asset in assets.values()], "sound_design": {"origin": "Original deterministic synthesis in renderer/study.py", "rights_status": "original", "source_sha256": sha256(raw_audio)}, "narration": {"present": False, "status": "intentional_voice_free_cut", "natural_voice_improvement_demonstrated": False}, "cost_usd": 0, "render_command": shlex.join(["python3", str(ROOT / "renderer/study.py"), "--brief", str(args.brief.resolve()), "--provenance", str(args.provenance.resolve()), "--output", str(output)]), "stock_context": "Licensed stock athletes illustrate training; they are not described as study participants or endorsers."}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    qc = qc_video(output, brief["duration_seconds"])
    qc["publication_blockers"] = ["Final script/video review absent", "Destination account and first-post workflow incomplete"]
    qc["audio_mode"] = "Original sound design; no narration"
    output.with_suffix(".qc.json").write_text(json.dumps(qc, indent=2) + "\n")
    stills = []
    review_beats = brief["beats"] if len(brief["beats"]) <= 12 else [brief["beats"][round(i * (len(brief["beats"]) - 1) / 11)] for i in range(12)]
    for index, beat in enumerate(review_beats):
        t = (beat["start"] + beat["end"]) / 2
        path = work / f"actual-frame-{index}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(output), "-frames:v", "1", str(path)])
        still = Image.open(path).convert("RGB"); still.thumbnail((216, 384)); stills.append(still.copy())
    sheet = Image.new("RGB", (216 * 4, 384 * 3), (16, 19, 19))
    for index, still in enumerate(stills):
        sheet.paste(still, ((index % 4) * 216, (index // 4) * 384))
    sheet.save(output.with_suffix(".contact.jpg"), quality=95)
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(output), "-frames:v", "1", str(output.with_suffix(".poster.jpg"))])
    print(json.dumps({"video": str(output), "duration": brief["duration_seconds"], "technical_qc_passed": qc["passed"], "publishable": False}, indent=2))
    if not qc["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
