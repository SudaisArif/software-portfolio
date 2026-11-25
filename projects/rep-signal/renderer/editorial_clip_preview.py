#!/usr/bin/env python3
"""A local, non-commercial NASA editorial preview with intact source speech.

This is deliberately separate from the rights-gated commercial clipping pipeline.
It neither grants rights nor registers an asset as cleared for distribution.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw

if __package__:
    from .render import ROOT, W, H, FPS, SR, font, qc_video, run, srt_time
    from .study import sha256, probe, SOURCE_INPUT_LIMITS
else:
    from render import ROOT, W, H, FPS, SR, font, qc_video, run, srt_time
    from study import sha256, probe, SOURCE_INPUT_LIMITS

SOURCE_START, SOURCE_END = 134.4, 170.601
EXCERPT_SECONDS = SOURCE_END - SOURCE_START
ENDCARD_SECONDS = 3
TOTAL_FRAMES = math.ceil((EXCERPT_SECONDS + ENDCARD_SECONDS) * FPS)
DURATION = TOTAL_FRAMES / FPS
CHALK, COPPER, MUTED = (241, 237, 228), (226, 143, 101), (178, 193, 185)


def parse_time(value):
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def captions_from_vtt(path):
    """Preserve source cue timing and words; repair documented text encoding."""
    cues = []
    for chunk in re.split(r"\n\s*\n", path.read_text().replace("\r\n", "\n")):
        match = re.search(r"(\d\d:\d\d:\d\d\.\d+) --> (\d\d:\d\d:\d\d\.\d+)\n(.+)", chunk, re.S)
        if not match:
            continue
        start, end = parse_time(match[1]), parse_time(match[2])
        if start >= SOURCE_START and end <= SOURCE_END:
            text = " ".join(match[3].split()).replace("í", "'").replace("your not having", "you're not having")
            cues.append({"start": round(start - SOURCE_START, 6), "end": round(end - SOURCE_START, 6), "text": text, "source_start": start, "source_end": end, "speaker": "Dr. Kjell Lindgren"})
    if not cues or not cues[0]["text"].startswith("When you stand up on Earth") or not cues[-1]["text"].endswith("weightlessness."):
        raise ValueError("Source captions do not match the complete intended excerpt")
    return cues


def lines(text, size=48, max_width=900):
    wrapped, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font(size, bold=True).getlength(candidate) > max_width:
            wrapped.append(current); current = word
        else:
            current = candidate
    if current:
        wrapped.append(current)
    if len(wrapped) > 3:
        raise ValueError("Source caption does not fit three readable lines")
    return wrapped


def frame(source_frame, seconds, cues):
    im = Image.new("RGB", (W, H), (15, 23, 22))
    draw = ImageDraw.Draw(im)
    draw.rectangle((84, 105, 90, 142), fill=COPPER)
    draw.text((110, 103), "REP SIGNAL / EDITORIAL PREVIEW", font=font(25, mono=True), fill=CHALK)
    draw.text((84, 187), "HUMAN VOICE · ORIGINAL SOURCE AUDIO", font=font(24, mono=True), fill=MUTED)
    title = ["YOUR MUSCLES", "IN SPACE."]
    for index, line in enumerate(title):
        draw.text((78, 260 + index * 104), line, font=font(88, bold=True), fill=COPPER if index else CHALK)
    # The whole 4:3 source is retained. A center crop would erase the astronaut,
    # explanatory animation or instruments when the source switches shots.
    source_frame = source_frame.resize((996, 747), Image.Resampling.LANCZOS)
    im.paste(source_frame, (42, 525))
    draw = ImageDraw.Draw(im)
    draw.text((84, 477), "NASA eClips · Our World: Exercise in Space", font=font(27), fill=MUTED)
    speaker_label = "Dr. Kjell Lindgren · source speaker" if seconds < EXCERPT_SECONDS else "Original editorial note · not speaker audio"
    draw.text((84, 1303), speaker_label, font=font(28), fill=MUTED)
    draw.rectangle((84, 1374, 174, 1380), fill=COPPER)
    if seconds < EXCERPT_SECONDS:
        cue = next((cue for cue in cues if cue["start"] <= seconds < cue["end"]), None)
        if cue:
            for index, line in enumerate(lines(cue["text"])):
                draw.text((84, 1414 + index * 67), line, font=font(48, bold=True), fill=CHALK)
    else:
        draw.rectangle((42, 525, 1038, 1272), fill=(19, 29, 27))
        draw.text((84, 589), "CONTEXT / REP SIGNAL", font=font(30, mono=True), fill=COPPER)
        for index, line in enumerate(("Extended unloading", "is not a normal", "rest day.")):
            draw.text((84, 741 + index * 92), line, font=font(69, bold=True), fill=CHALK)
    draw.text((84, 1651), "Source excerpt: 02:14.400–02:50.601", font=font(24, mono=True), fill=MUTED)
    draw.text((84, 1694), "NASA is not an endorser of REP SIGNAL.", font=font(24), fill=MUTED)
    draw.text((84, 1740), "LOCAL REVIEW · COMMERCIAL RELEASE UNRESOLVED", font=font(19, mono=True), fill=MUTED)
    draw.rectangle((84, 1800, 996, 1804), fill=(60, 79, 70))
    draw.rectangle((84, 1800, 84 + round(912 * seconds / DURATION), 1804), fill=COPPER)
    return im


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provenance", type=Path, default=ROOT / "assets/footage/nasa-editorial-provenance.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/human-clip-preview.mp4")
    args = parser.parse_args(argv)
    provenance = json.loads(args.provenance.read_text())
    source = (ROOT / provenance["source_path"]).resolve()
    captions = (ROOT / provenance["captions_path"]).resolve()
    for path, key in ((source, "source_sha256"), (captions, "captions_sha256")):
        if not path.is_relative_to(ROOT / "assets/footage") or sha256(path) != provenance[key]:
            raise ValueError("Source path or checksum differs from the reviewed provenance")
    if provenance.get("rights_status") != "preview_only" or provenance.get("commercial_use_attested") is not False:
        raise ValueError("This renderer only supports the documented editorial preview")
    cues = captions_from_vtt(captions)
    for cue in cues:
        lines(cue["text"])
    source_probe = probe(source)
    if float(source_probe["format"]["duration"]) < SOURCE_END or not any(s["codec_type"] == "audio" for s in source_probe["streams"]):
        raise ValueError("Source lacks the complete audiovisual excerpt")
    output = args.output.resolve(); output.parent.mkdir(exist_ok=True, parents=True)
    work = output.parent / ".human-clip-cache"; work.mkdir(exist_ok=True)
    audio = work / "source-speech.wav"
    run(["ffmpeg", "-y", "-v", "error", *SOURCE_INPUT_LIMITS, "-ss", str(SOURCE_START), "-i", str(source), "-t", str(EXCERPT_SECONDS), "-vn", "-af", "loudnorm=I=-16:TP=-1.8:LRA=9", "-ar", str(SR), "-ac", "2", str(audio)])
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(audio), "-af", "apad", "-t", str(DURATION), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(output)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    decoder = subprocess.Popen(["ffmpeg", "-v", "error", *SOURCE_INPUT_LIMITS, "-ss", str(SOURCE_START), "-i", str(source), "-t", str(EXCERPT_SECONDS), "-an", "-vf", f"fps={FPS},scale=640:480", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last = None
    try:
        for index in range(TOTAL_FRAMES):
            t = index / FPS
            if t < EXCERPT_SECONDS:
                raw = decoder.stdout.read(640 * 480 * 3)
                if len(raw) == 640 * 480 * 3:
                    last = Image.frombytes("RGB", (640, 480), raw)
                elif t < EXCERPT_SECONDS - 1 / FPS:
                    raise RuntimeError("Source footage ended early")
            if last is None:
                raise RuntimeError("Source video is empty")
            encoder.stdin.write(frame(last, t, cues).tobytes())
    finally:
        decoder.stdout.close(); encoder.stdin.close()
    for process in (decoder, encoder):
        error = process.stderr.read().decode(); process.stderr.close()
        if process.wait():
            raise RuntimeError(error)
    for path, key in ((source, "source_sha256"), (captions, "captions_sha256")):
        if sha256(path) != provenance[key]:
            output.unlink(missing_ok=True)
            raise ValueError("Source video or captions changed during rendering; draft discarded")
    output.with_suffix(".srt").write_text("\n\n".join(f"{index+1}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{cue['text']}" for index, cue in enumerate(cues)) + f"\n\n{len(cues)+1}\n{srt_time(EXCERPT_SECONDS)} --> {srt_time(DURATION)}\n[REP SIGNAL editorial note]\nExtended unloading is not a normal rest day.\n")
    manifest = {"title": "Your muscles in space — real human speech preview", "format": "editorial_source_clip_preview", "status": "LOCAL_REVIEW_SAMPLE", "rights_status": "preview_only", "commercial_release_unresolved": True, "commercial_use_attested": False, "publishable": False, "human_approved": False, "duration_seconds": DURATION, "dimensions": [W, H], "fps": FPS, "narration_mode": "original_human_source_audio", "speaker": "Dr. Kjell Lindgren", "script": " ".join(cue["text"] for cue in cues), "script_kind": "official_source_caption_transcript", "original_editorial_note": "Extended unloading is not a normal rest day.", "source_excerpt": {"start": SOURCE_START, "end": SOURCE_END, "continuous": True, "speed": 1, "speech_synthesis": False, "voice_cloning": False, "audio_changes": "Loudness normalization and resampling only; no word removal, reordering or generated speech", "picture_changes": "Full4:3 image upscaled within portrait frame; source image not cropped"}, "captions": cues, "provenance": provenance, "sources": [{"title": provenance["title"], "url": provenance["source_url"]}], "factual_caveat": "The speaker describes prolonged unloading and weightlessness. The excerpt is not evidence that a normal recovery day is harmful.", "review": {"decoded_frames_inspected": False, "human_listening_review": "pending; this environment cannot perceive audio", "caption_basis": "Official VTT with documented apostrophe/orthographic repairs; source timing preserved"}, "render_command": "python3 renderer/editorial_clip_preview.py", "cost_usd": 0}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    qc = qc_video(output, DURATION, external_narration=True)
    qc["publication_blockers"] = ["Editorial preview only; commercial release unresolved", "Identifiable-person and underlying-material rights not cleared for commercial use", "Human listening and final-video review pending"]
    qc["audio_mode"] = "Actual continuous source speech; no synthetic narrator"
    output.with_suffix(".qc.json").write_text(json.dumps(qc, indent=2) + "\n")
    sheet = Image.new("RGB", (864, 768), (15, 23, 22))
    for index, at in enumerate((1, 7, 13, 19, 25, 31, 35, 38)):
        path = work / f"preview-actual-{index}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(output), "-frames:v", "1", str(path)])
        still = Image.open(path).convert("RGB"); still.thumbnail((216, 384))
        sheet.paste(still, ((index % 4) * 216, (index // 4) * 384))
    sheet.save(output.with_suffix(".contact.jpg"), quality=95)
    run(["ffmpeg", "-y", "-v", "error", "-ss", "21", "-i", str(output), "-frames:v", "1", str(output.with_suffix(".poster.jpg"))])
    print(json.dumps({"video": str(output), "duration_seconds": DURATION, "technical_qc_passed": qc["passed"], "rights_status": "preview_only", "publishable": False}, indent=2))
    if not qc["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
