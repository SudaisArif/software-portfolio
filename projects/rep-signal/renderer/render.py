#!/usr/bin/env python3
"""Render original portrait films with segment-timed narration and captions.

Requires Python 3.11+, Pillow, NumPy, FFmpeg and (for the local preview voice)
macOS `say`. No API, download, account, or publishing operation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS, SR = 1080, 1920, 24, 48000
STYLES = ("cinematic", "editorial", "storytelling")
SEGMENTS = [
    ("Tomorrow, I'll train.", "THE NEXT\nREP", "01 / THE PROMISE"),
    ("A promise can be clear. And the next step can still be missing.", "STARTS\nBEFORE\nTHE GYM.", "01 / THE PROMISE"),
    ("Give it a place.", "GIVE IT\nA PLACE.", "02 / THE CUE"),
    ("At six, after class, I'll walk through the gym doors.", "18:00\nAFTER CLASS.", "02 / THE CUE"),
    ("Then give it a first move.", "ONE\nFIRST MOVE.", "03 / THE ACTION"),
    ("Bag down. Phone away. Warm-up set.", "BAG DOWN.\nPHONE AWAY.\nWARM-UP SET.", "03 / THE ACTION"),
    ("A specific plan won't lift the weight for you.", "THE WORK\nIS STILL\nYOURS.", "04 / THE LIMIT"),
    ("It's one decision to try when the day gets loud.", "LESS TO\nFIGURE OUT.", "04 / THE LIMIT"),
    ("Choose the cue. Name the next action.", "CHOOSE\nTHE CUE.", "05 / THE NEXT REP"),
    ("Then make that action real.", "MAKE\nIT REAL.", "05 / THE NEXT REP"),
]
SOURCES = [
    {"title": "Combining motivational and volitional interventions to promote exercise participation", "authors": "Milne, Orbell & Sheeran", "year": 2002, "url": "https://doi.org/10.1348/135910702169420", "scope": "A short-term experiment found benefits of combined motivation and implementation planning. No numerical claim is made in this film."},
    {"title": "The Limits of Simple Implementation Intentions: Evidence from a Field Experiment on Making Plans to Exercise", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7872013/", "scope": "Counterevidence: simple plans did not increase gym attendance in this field experiment. The film frames planning as a practical experiment, not a guarantee."},
]


def run(args: list[str], **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def probe(path: Path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)


def font_path(bold=False, mono=False):
    bundled = ROOT / "assets/fonts" / ("DejaVuSansMono.ttf" if mono else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    if bundled.is_file():
        return str(bundled)
    candidates = (["/Library/Fonts/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"] if mono else
                  ["/Library/Fonts/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
                  ["/Library/Fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for name in candidates:
        if Path(name).is_file():
            return name
    raise RuntimeError("Install DejaVu Sans fonts before rendering. No font will be silently substituted.")


FONTS = {}
def font(size, bold=False, mono=False):
    key = (size, bold, mono)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(font_path(bold, mono), size)
    return FONTS[key]


def smooth(v):
    v = min(1.0, max(0.0, v))
    return v * v * (3 - 2 * v)


def srt_time(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def caption_chunks(text: str, max_chars=40) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines


def prepare_audio(work: Path, voice: str, rate: int, segments=None):
    """Each caption cue uses the measured boundaries of one spoken segment."""
    if not shutil.which("say"):
        raise RuntimeError("The local preview voice requires macOS say. Supply a licensed voice adapter before production.")
    timeline, speech = [], [np.zeros(round(SR * .55), dtype=np.float32)]
    cursor = .55
    for index, (text, title, chapter) in enumerate(segments or SEGMENTS):
        cache_key = hashlib.sha256(f"{voice}|{rate}|{text}".encode()).hexdigest()[:12]
        aiff, wav = work / f"voice-{cache_key}.aiff", work / f"voice-{cache_key}.wav"
        if not wav.exists() or wav.stat().st_size < 128:
            run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text])
            run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        with wave.open(str(wav), "rb") as f:
            data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        # Remove only surplus digital silence, preserving speech consonants.
        active = np.flatnonzero(np.abs(data) > .002)
        if not len(active):
            raise ValueError("Narration segment is silent")
        data = data[max(0, active[0] - int(.035 * SR)):min(len(data), active[-1] + int(.14 * SR))]
        end = cursor + len(data) / SR
        timeline.append({"index": index, "start": round(cursor, 4), "end": round(end, 4), "text": text, "title": title, "chapter": chapter})
        speech.append(data)
        gap = .38 if index in (1, 3, 5, 7) else .22
        speech.append(np.zeros(round(gap * SR), dtype=np.float32))
        cursor = end + gap
    speech.append(np.zeros(round(1.2 * SR), dtype=np.float32))
    narration = np.concatenate(speech)
    return mix_audio(work, narration, timeline)


def canonical_characters(text: str):
    """Collapse whitespace without changing word boundaries; retain source indices."""
    chars, indices, pending_space = [], [], None
    for index, character in enumerate(text):
        if character.isspace():
            if chars and pending_space is None:
                pending_space = index
            continue
        if pending_space is not None:
            chars.append(" "); indices.append(pending_space)
            pending_space = None
        chars.append(character); indices.append(index)
    return "".join(chars), indices


def aligned_timeline(payload: dict, segments: list, audio_duration: float) -> list[dict]:
    """Validate ElevenLabs character alignment and map it to exact script segments.

    Accepts an alignment object or a full response containing `alignment`.
    A normalized alignment is accepted only if its complete text still matches.
    Whitespace is normalized; punctuation, case, numbers and words are not.
    """
    if not isinstance(payload, dict):
        raise ValueError("Alignment must be a JSON object")
    if "characters" in payload:
        alignment = payload
    else:
        alignment = payload.get("alignment") or payload.get("normalized_alignment")
    if not isinstance(alignment, dict):
        raise ValueError("Alignment requires characters and character start/end timestamps")
    chars = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not all(isinstance(values, list) for values in (chars, starts, ends)):
        raise ValueError("Character alignment arrays are missing")
    if not chars or len(chars) > 20000 or not len(chars) == len(starts) == len(ends):
        raise ValueError("Character alignment arrays must have equal nonzero lengths")
    if any(not isinstance(character, str) or len(character) != 1 for character in chars):
        raise ValueError("Each alignment character must be a single Unicode character")
    if not isinstance(audio_duration, (int, float)) or not math.isfinite(audio_duration) or audio_duration <= 0:
        raise ValueError("Audio duration must be finite and positive")
    previous_end = 0.0
    for start, end in zip(starts, ends):
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, end)):
            raise ValueError("Alignment timestamps must be finite numbers")
        if start < 0 or end < start or start + .00001 < previous_end or end > audio_duration + .05:
            raise ValueError("Alignment timestamps overlap, run backwards, or exceed the audio duration")
        previous_end = end
    aligned_text, source_indices = canonical_characters("".join(chars))
    segment_texts = [canonical_characters(segment[0])[0] for segment in segments]
    if not segments or any(not text for text in segment_texts):
        raise ValueError("Narration segments must contain text")
    expected = " ".join(segment_texts)
    if aligned_text != expected:
        raise ValueError("Narration alignment text does not exactly match the script (apart from whitespace)")
    timeline, cursor = [], 0
    for index, ((text, title, chapter), normalized) in enumerate(zip(segments, segment_texts)):
        first, last = source_indices[cursor], source_indices[cursor + len(normalized) - 1]
        start, end = float(starts[first]), min(audio_duration, float(ends[last]))
        if end <= start:
            raise ValueError("Every narration segment requires a positive aligned duration")
        timeline.append({"index": index, "start": round(start, 6), "end": round(end, 6), "text": text, "title": title, "chapter": chapter, "timing_source": "supplied_character_alignment"})
        cursor += len(normalized) + 1
    return timeline


def prepare_aligned_audio(work: Path, narration_path: Path, alignment_path: Path, segments: list):
    """Decode externally generated narration without shifting or trimming timestamps."""
    if not narration_path.is_file() or not alignment_path.is_file():
        raise ValueError("Both narration and alignment must be existing local files")
    info = probe(narration_path)
    if not any(stream.get("codec_type") == "audio" for stream in info["streams"]):
        raise ValueError("Narration input contains no audio stream")
    source_duration = float(info["format"].get("duration", 0))
    if not math.isfinite(source_duration) or not 0 < source_duration <= 90.05:
        raise ValueError("Supplied narration must be at most 90 seconds")
    payload = json.loads(alignment_path.read_text())
    # Validate text and timestamps before spending time on audio conversion.
    aligned_timeline(payload, segments, source_duration)
    digest = hashlib.sha256(narration_path.read_bytes() + alignment_path.read_bytes()).hexdigest()[:16]
    isolated_work = work / f"external-{digest}"
    isolated_work.mkdir(parents=True, exist_ok=True)
    decoded = isolated_work / "narration.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(narration_path), "-map", "0:a:0", "-t", "90.05", "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(decoded)])
    with wave.open(str(decoded), "rb") as source:
        narration = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if not len(narration) or np.max(np.abs(narration)) < .002:
        raise ValueError("Supplied narration is empty or silent")
    duration = len(narration) / SR
    timeline = aligned_timeline(payload, segments, duration)
    return mix_audio(isolated_work, narration, timeline)


def mix_audio(work: Path, narration: np.ndarray, timeline: list[dict]):
    """Add the original sound bed and normalize without changing narration timing."""
    duration = len(narration) / SR
    t = np.arange(len(narration), dtype=np.float32) / SR
    # Original mathematical sound design. No samples or third-party music.
    swell = np.minimum(t / 2, 1) * np.minimum((duration - t) / 2, 1)
    bed = (.021 * np.sin(2 * np.pi * 55 * t) + .011 * np.sin(2 * np.pi * 82.4069 * t) + .006 * np.sin(2 * np.pi * 110.1 * t)) * swell
    pulse = ((1 + np.cos(2 * np.pi * t / 2.5)) / 2) ** 9
    bed += .025 * np.sin(2 * np.pi * (46 * t + .5 * np.sin(2 * np.pi * .1 * t))) * pulse * swell
    rng = np.random.default_rng(41)
    bed += rng.normal(0, .0007, len(t)).astype(np.float32) * swell
    for segment in timeline:
        delta = t - segment["start"]
        envelope = np.where(delta >= 0, np.exp(-np.maximum(delta, 0) * 8), 0)
        bed += .012 * envelope * np.sin(2 * np.pi * 440 * delta)
    mix = narration * .81 + bed
    peak = float(np.max(np.abs(mix)))
    if peak > .9:
        mix *= .9 / peak
    raw = work / "mix.wav"
    with wave.open(str(raw), "wb") as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
        stereo = np.column_stack((mix, mix))
        f.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())
    out = work / "audio.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", "loudnorm=I=-16:TP=-1.5:LRA=9", "-ar", str(SR), str(out)])
    return timeline, duration, out


def cylinder(x0, x1, radius, color, facets=40):
    faces = []
    for i in range(facets):
        a, b = i * 2 * math.pi / facets, (i + 1) * 2 * math.pi / facets
        yz = lambda x, q: (x, radius * math.cos(q), radius * math.sin(q))
        faces.append((np.array([yz(x0, a), yz(x1, a), yz(x1, b), yz(x0, b)]), np.array([0, math.cos((a+b)/2), math.sin((a+b)/2)]), color))
    for x, sign in ((x0, -1), (x1, 1)):
        for i in range(facets):
            a, b = i * 2 * math.pi / facets, (i + 1) * 2 * math.pi / facets
            faces.append((np.array([(x, 0, 0), (x, radius * math.cos(a), radius * math.sin(a)), (x, radius * math.cos(b), radius * math.sin(b))]), np.array([sign, 0, 0]), color))
    return faces


MESH = cylinder(-4.4, 4.4, .095, (133, 144, 150), 24)
for side in (-1, 1):
    for i, radius in enumerate((1.23, 1.20, 1.07)):
        x = side * (2.5 + i * .31)
        MESH += cylinder(x - .13, x + .13, radius, (50 + i * 9, 57 + i * 9, 60 + i * 9), 48)
        MESH += cylinder(x + side * .14, x + side * .16, radius * .96, (142, 119, 75), 48)
        MESH += cylinder(x + side * .17, x + side * .19, radius * .89, (36, 42, 44), 48)
    MESH += cylinder(side * 3.6 - .12, side * 3.6 + .12, .25, (158, 166, 166), 24)


def draw_barbell(draw, t, center, scale, style):
    ay, az, ax = .55 + .11 * math.sin(t * .2), -.34 + .035 * math.cos(t * .24), .24
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    rotation = rz @ rx @ ry
    light = np.array([-.35, -.65, .7]); light /= np.linalg.norm(light)
    faces = []
    for points, normal, color in MESH:
        transformed = points @ rotation.T
        normal = rotation @ normal
        if normal[2] <= 0:
            continue
        shade = max(.17, float(np.dot(normal, light)) * .8 + .25)
        perspective = 1 / (1 - transformed[:, 2] / 15)
        projected = transformed[:, :2] * perspective[:, None] * scale
        projected += center
        fill = tuple(min(255, round(c * shade)) for c in color)
        faces.append((float(transformed[:, 2].mean()), projected, fill))
    for _, polygon, fill in sorted(faces, key=lambda f: f[0]):
        if style == "editorial":
            draw.polygon([tuple(p) for p in polygon], fill=(222, 218, 207), outline=(62, 64, 60))
        else:
            draw.polygon([tuple(p) for p in polygon], fill=fill)


BG = {}
def background(style):
    if style in BG:
        return BG[style].copy()
    y, x = np.mgrid[0:H, 0:W]
    radial = np.exp(-((x - W * .4) ** 2 / (W * .55) ** 2 + (y - H * .43) ** 2 / (H * .4) ** 2))
    noise = np.random.default_rng(12).normal(0, 1.15, (H, W))
    base, light = ((13, 18, 20), (20, 26, 25)) if style == "cinematic" else ((229, 226, 215), (15, 14, 9)) if style == "editorial" else ((7, 18, 30), (9, 24, 34))
    arr = np.stack([np.clip(base[i] + radial * light[i] + noise, 0, 255) for i in range(3)], axis=2).astype(np.uint8)
    BG[style] = Image.fromarray(arr)
    return BG[style].copy()


def draw_runner(draw, t, center, size, ink, accent):
    """An original schematic athlete in motion, not a real person's likeness."""
    x, y = center
    phase = t * 3.6
    head = (x + size * .1, y - size * .75)
    hip = (x, y)
    shoulder = (x + size * .14, y - size * .51)
    draw.ellipse((head[0] - size * .12, head[1] - size * .12, head[0] + size * .12, head[1] + size * .12), fill=ink)
    draw.line((shoulder, hip), fill=ink, width=round(size * .14))
    for sign in (-1, 1):
        swing = math.sin(phase + (0 if sign == 1 else math.pi))
        knee = (x + swing * size * .44, y + size * .37)
        foot = (knee[0] - math.cos(phase) * sign * size * .36, y + size * (.70 - max(swing, 0) * .18))
        elbow = (shoulder[0] - swing * size * .33, shoulder[1] + size * .21)
        hand = (elbow[0] + size * .24, elbow[1] - size * .13)
        color = ink if sign == 1 else accent
        draw.line((hip, knee, foot), fill=color, width=round(size * .095), joint="curve")
        draw.line((shoulder, elbow, hand), fill=color, width=round(size * .065), joint="curve")


def frame(t: float, timeline: list[dict], duration: float, style: str) -> Image.Image:
    im = background(style); d = ImageDraw.Draw(im)
    segment = next((s for s in timeline if t < s["end"]), timeline[-1])
    elapsed = max(0, t - segment["start"])
    title_opacity = smooth(elapsed / .35)
    ink = (239, 237, 225) if style != "editorial" else (30, 37, 34)
    muted = (125, 141, 138) if style != "editorial" else (90, 101, 92)
    accent = (199, 116, 81) if style == "cinematic" else (204, 82, 46) if style == "editorial" else (125, 215, 210)
    # The owner selected REP SIGNAL; publication still requires separate approval.
    d.rectangle((92, 94, 100, 133), fill=accent)
    d.text((120, 92), "REP SIGNAL", font=font(28, mono=True), fill=ink)
    d.text((92, 166), segment["chapter"], font=font(23, mono=True), fill=muted)
    title = segment["title"].split("\n")
    title_size = 113 if max(map(len, title)) < 11 else 88
    if style == "editorial":
        title_size = 105 if max(map(len, title)) < 11 else 84
    for i, line in enumerate(title):
        # A brief rise reveals each line while the underlying scene keeps moving.
        d.text((88, 244 + i * (title_size + 9) + round((1-title_opacity)*22)), line, font=font(title_size, bold=True), fill=ink)
    if style == "cinematic":
        floor_y = 1290
        # Perspective grid and drifting point field evoke an empty training floor.
        for i in range(-7, 8):
            d.line((540 + i * 40, 970, 540 + i * 310, 1360), fill=(27, 38, 39), width=1)
        for i in range(7):
            y = 1000 + ((i / 7 + (t * .018)) % 1) ** 2 * 350
            d.line((70, y, 980, y), fill=(29, 41, 40), width=1)
        float_y = 965 - 45 * math.sin(t * .36)
        for k in range(5):
            r = 210 + k * 22
            d.ellipse((540-r, floor_y-20-k*3, 540+r, floor_y+20+k*3), outline=(23+k, 31+k, 31+k), width=2)
        draw_barbell(d, t, (540 + 15*math.sin(t*.18), float_y), 116 + 5*math.sin(t*.12), style)
        for i in range(28):
            px = 100 + ((i * 213.17 + t * (3 + i % 4)) % 875)
            py = 670 + ((i * 71.37 - t * 7) % 640)
            c = 58 + i % 25
            d.ellipse((px, py, px+2, py+2), fill=(c, c, c-8))
        d.line((92, 1355, 400, 1355), fill=accent, width=2)
        d.text((92, 1375), "INTENTION → ACTION", font=font(23, mono=True), fill=muted)
    elif style == "editorial":
        for gx in range(92, 990, 64):
            for gy in range(690, 1370, 64):
                d.ellipse((gx, gy, gx+2, gy+2), fill=(184, 186, 173))
        nodes = [(120, 800, "WHEN", "18:00"), (510, 800, "WHERE", "GYM"), (120, 1110, "FIRST ACTION", "WARM-UP")]
        growth = (t * .2) % 1
        d.line((160, 940, 160, 1000, 590, 1000, 590, 1065, 160, 1065, 160, 1110), fill=(153, 164, 147), width=4)
        d.ellipse((160+430*growth-9, 991, 160+430*growth+9, 1009), fill=accent)
        for i, (x, y, label, value) in enumerate(nodes):
            d.rectangle((x, y, x+345, y+140), fill=(229, 226, 215), outline=(106, 119, 105), width=2)
            d.text((x+19, y+17), label, font=font(22, mono=True), fill=muted)
            d.text((x+19, y+66), value, font=font(40, bold=True), fill=ink)
        d.text((120, 1335), "A PLAN IS AN EXPERIMENT.", font=font(25, mono=True), fill=accent)
    else:
        # Track lanes slide under a schematic athlete. This is an illustrative
        # vignette; it makes no biographical claim about a real athlete.
        for i in range(-2, 7):
            x = 100 + i*210
            d.line((x, 680, x-500, 1370), fill=(37, 66, 82), width=3)
        for i in range(8):
            y = 700 + ((i*100+t*75) % 650)
            d.line((90, y, 980, y), fill=(23, 46, 60), width=1)
        draw_runner(d, t, (530, 1030 + 5*math.sin(t*7.2)), 240, ink, (66, 117, 135))
        d.text((92, 1325), "AN ILLUSTRATED TRAINING VIGNETTE", font=font(23, mono=True), fill=accent)
    # Caption blocks remain inside conservative shared-platform safe margins.
    d.line((92, 1450, 890, 1450), fill=muted, width=1)
    if segment["start"] <= t <= segment["end"]:
        lines = caption_chunks(segment["text"], 36)
        for i, line in enumerate(lines):
            d.text((92, 1486 + i*59), line, font=font(43, bold=False), fill=ink)
    d.text((92, 1715), "REP SIGNAL  /  FILM 001", font=font(22, mono=True), fill=muted)
    # Small on-video review marker prevents accidental presentation as cleared.
    d.text((92, 1760), "LOCAL REVIEW · VOICE PREVIEW", font=font(18, mono=True), fill=muted)
    d.rectangle((92, 1815, 890, 1818), fill=(65, 75, 71) if style != "editorial" else (174, 178, 162))
    d.rectangle((92, 1815, 92+798*min(1,t/duration), 1818), fill=accent)
    # Gentle overall fade; no flashing cuts.
    fade = smooth(t/.45) * smooth((duration-t)/.65)
    if fade < 1:
        im = Image.blend(Image.new("RGB", (W,H), (10,14,16) if style != "editorial" else (229,226,215)), im, fade)
    return im


def qc_video(path: Path, expected_duration: float, external_narration=False):
    info = probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    duration = float(info["format"]["duration"])
    checks = {
        "portrait_1080x1920": (video["width"],video["height"]) == (1080,1920),
        "h264": video["codec_name"] == "h264",
        "aac": audio["codec_name"] == "aac",
        "yuv420p": video["pix_fmt"] == "yuv420p",
        "stereo_48khz": audio["channels"] == 2 and audio["sample_rate"] == "48000",
        "duration_matches": abs(duration-expected_duration) < .2,
    }
    loud = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json", "-f", "null", "-"]).stderr.decode()
    match = re.search(r'\{\s*"input_i".*?\}', loud, re.S)
    levels = json.loads(match.group()) if match else {}
    checks["audible_loudness"] = -19 <= float(levels.get("input_i", -100)) <= -13
    checks["true_peak_below_minus_1db"] = float(levels.get("input_tp", 100)) <= -1
    narration_blocker = "Supplied narration: licensing evidence must be verified by the production approval pipeline" if external_narration else "Local system narration voice: commercial rights not reviewed"
    return {"passed": all(checks.values()), "checks": checks, "duration_seconds": duration, "loudness": levels, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "publication_eligible": False, "publication_blockers": ["Human script and final-video approval absent", narration_blocker, "Destination accounts and first publication not authorized"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", choices=STYLES, default="cinematic")
    parser.add_argument("--output", type=Path, default=ROOT/"output/sample.mp4")
    parser.add_argument("--voice", default="Daniel")
    parser.add_argument("--system-voice-preview", action="store_true", help="Explicitly opt into the archived macOS timing-preview voice; never production narration")
    parser.add_argument("--rate", type=int, default=150)
    parser.add_argument("--brief", type=Path, help="JSON brief with title, sources, and segments [{text,title,chapter}]")
    parser.add_argument("--narration", type=Path, help="Prerecorded narration audio; requires --alignment")
    parser.add_argument("--alignment", type=Path, help="ElevenLabs character alignment JSON; requires --narration")
    parser.add_argument("--preview-seconds", type=float)
    parser.add_argument("--poster-only", action="store_true")
    parser.add_argument("--audio-only", action="store_true", help="Prepare the local preview narration without rendering frames")
    args = parser.parse_args(argv)
    if bool(args.narration) != bool(args.alignment):
        parser.error("--narration and --alignment must be supplied together")
    if not args.narration and not args.system_voice_preview:
        parser.error("Supply human/licensed --narration and --alignment. The archived voice requires explicit --system-voice-preview; use renderer/study.py for the real-footage visual preview.")
    if args.preview_seconds is not None and (not math.isfinite(args.preview_seconds) or args.preview_seconds <= 0):
        parser.error("--preview-seconds must be finite and positive")
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            parser.error(f"{binary} is required")
    out = args.output.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / ".render-cache"; work.mkdir(exist_ok=True)
    segments, sources, film_title = SEGMENTS, SOURCES, "The next rep"
    if args.brief:
        brief = json.loads(args.brief.read_text())
        if not isinstance(brief.get("segments"), list) or not 3 <= len(brief["segments"]) <= 30:
            parser.error("A brief requires 3–30 segments")
        segments = []
        for item in brief["segments"]:
            values = tuple(item.get(key) for key in ("text", "title", "chapter"))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                parser.error("Each segment requires nonempty text, title, and chapter strings")
            text, title, chapter = values
            if len(text) > 110 or len(title.splitlines()) > 3 or any(len(line) > 12 for line in title.splitlines()) or len(chapter) > 35:
                parser.error("Split long narration or titles into more segments to keep captions and headings in frame")
            segments.append(values)
        sources = brief.get("sources", [])
        film_title = str(brief.get("title", "Local review sample"))
    if args.narration:
        try:
            timeline, full_duration, audio_path = prepare_aligned_audio(work, args.narration, args.alignment, segments)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        narration_asset = {"kind": "narration", "origin": "supplied_prerecorded_audio", "rights_status": "requires_external_license_verification", "source_path": str(args.narration.resolve()), "source_sha256": hashlib.sha256(args.narration.read_bytes()).hexdigest(), "alignment_path": str(args.alignment.resolve()), "alignment_sha256": hashlib.sha256(args.alignment.read_bytes()).hexdigest()}
    else:
        timeline, full_duration, audio_path = prepare_audio(work, args.voice, args.rate, segments)
        narration_asset = {"kind": "narration", "origin": f"macOS say / {args.voice}", "rights_status": "preview_only_not_cleared_for_publication"}
    if full_duration > 90 or (full_duration < 20 and args.preview_seconds is None):
        parser.error(f"Narration duration is {full_duration:.1f}s; full films require 20–90 seconds (short technical tests require --preview-seconds)")
    if args.audio_only:
        print(json.dumps({"audio": str(audio_path), "duration_seconds": full_duration, "narration": narration_asset})); return
    duration = min(full_duration, args.preview_seconds) if args.preview_seconds else full_duration
    if not 0 < duration <= 90:
        parser.error("Render duration must be 0–90 seconds")
    poster_path = out.with_suffix(".poster.jpg")
    frame(min(2, duration/2), timeline, full_duration, args.style).save(poster_path, quality=95)
    if args.poster_only:
        print(json.dumps({"poster": str(poster_path)})); return
    ffmpeg_args = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(audio_path), "-t", str(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(out)]
    process = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    total_frames = math.ceil(duration * FPS)
    try:
        for number in range(total_frames):
            process.stdin.write(frame(number/FPS, timeline, full_duration, args.style).tobytes())
            if number % (FPS*5) == 0:
                print(f"Rendered {number/FPS:.0f}/{duration:.1f}s", file=sys.stderr, flush=True)
    finally:
        process.stdin.close()
    stderr = process.stderr.read().decode()
    process.stderr.close()
    if process.wait() != 0:
        raise RuntimeError(stderr)
    captions = [s for s in timeline if s["start"] < duration]
    out.with_suffix(".srt").write_text("\n\n".join(f'{i+1}\n{srt_time(s["start"])} --> {srt_time(min(s["end"], duration))}\n{s["text"]}' for i,s in enumerate(captions))+"\n")
    metadata = {"title": film_title, "style": args.style, "status": "LOCAL_REVIEW_SAMPLE", "human_approved": False, "publishable": False, "dimensions": [W,H], "fps": FPS, "duration_seconds": duration, "script": " ".join(s[0] for s in segments), "timeline": timeline, "sources": sources, "factual_caveat": "Planning does not guarantee exercise adherence; this film suggests an experiment. Voice and visuals portray no real individual.", "assets": [{"kind": "visuals", "origin": "Original procedural geometry and motion authored in renderer/render.py", "rights_status": "original", "third_party_footage": False}, {"kind": "sound_design", "origin": "Original synthesized sine waves, envelopes and deterministic noise", "rights_status": "original"}, narration_asset, {"kind": "font", "origin": "DejaVu Sans", "license": "Bitstream Vera/DejaVu license", "license_file": "assets/licenses/DejaVu-LICENSE.txt"}], "render_command": f"python3 renderer/render.py --style {args.style} --output {out}", "brief_path": str(args.brief) if args.brief else None, "cost_usd": 0, "cost_scope": "local rendering only; excludes creation or licensing of supplied narration"}
    out.with_suffix(".json").write_text(json.dumps(metadata, indent=2))
    qc = qc_video(out, duration, external_narration=bool(args.narration))
    out.with_suffix(".qc.json").write_text(json.dumps(qc, indent=2))
    # Contact sheet uses actual decoded output frames, not only source frames.
    stills = []
    for i, fraction in enumerate((.07,.24,.42,.59,.76,.91)):
        path = work/f"qa-{args.style}-{i}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(duration*fraction), "-i", str(out), "-frames:v", "1", str(path)])
        image = Image.open(path).convert("RGB"); image.thumbnail((270,480)); stills.append(image.copy())
    sheet = Image.new("RGB", (810,960))
    for i,image in enumerate(stills): sheet.paste(image,((i%3)*270,(i//3)*480))
    sheet.save(out.with_suffix(".contact.jpg"), quality=94)
    print(json.dumps({"video": str(out), "poster": str(poster_path), "duration": duration, "technical_qc_passed": qc["passed"], "publishable": False}, indent=2))
    if not qc["passed"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
