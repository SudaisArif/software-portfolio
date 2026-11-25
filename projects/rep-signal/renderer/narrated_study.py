"""Local-only, exact-audio editorial study renderer. Does not generate narration."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw

if __package__:
    from .render import ROOT, W, H, FPS, SR, font, font_path, qc_video, run, srt_time
    from .study import COPPER, CHALK, MUTED, finite, sha256, verify_assets, decode_frames, soundbed
else:
    from render import ROOT, W, H, FPS, SR, font, font_path, qc_video, run, srt_time
    from study import COPPER, CHALK, MUTED, finite, sha256, verify_assets, decode_frames, soundbed

INK = (9, 17, 18)
TEAL = (130, 201, 187)


def canonical(text):
    return " ".join(text.split())


def heading_size(titles):
    for size in range(83, 60, -2):
        if all(font(size, bold=True).getlength(line) <= 841 for line in titles):
            return size
    raise ValueError("Editorial title is wider than the portrait safe area")


def validate_alignment(script, alignment, wav_path):
    """Reject mismatched audio/text, invented timings and clipped speech."""
    with wave.open(str(wav_path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE" or audio.getnchannels() not in (1, 2):
            raise ValueError("Narration must be mono/stereo PCM16 WAV")
        duration = audio.getnframes() / audio.getframerate()
    if not 60 <= duration <= 90:
        raise ValueError("Narrated review audio must last 60–90 seconds")
    if alignment.get("audio_sha256") != sha256(wav_path):
        raise ValueError("Alignment audio checksum does not match narration")
    stated = alignment.get("duration_seconds")
    if not finite(stated) or abs(stated - duration) > .05:
        raise ValueError("Alignment duration does not match WAV")
    segments = alignment.get("segments")
    expected = script.get("segments")
    if not isinstance(segments, list) or not expected or len(segments) != len(expected):
        raise ValueError("Every script segment requires an aligned sentence")
    previous = 0.0
    for item, target in zip(segments, expected):
        if item.get("id") != target["id"] or canonical(item.get("text", "")) != canonical(target["text"]):
            raise ValueError("Alignment text/ID differs from the exact narration script")
        start, end = item.get("start"), item.get("end")
        if not all(finite(v) for v in (start, end)) or start < previous - .001 or not start < end <= duration + .001:
            raise ValueError("Invalid or overlapping sentence timings")
        previous = end
        words = item.get("words", [])
        if words:
            if canonical(" ".join(w.get("text", "") for w in words)) != canonical(item["text"]):
                raise ValueError("Word alignment differs from sentence text")
            previous_word = start
            for word in words:
                a, b = word.get("start"), word.get("end")
                if not all(finite(v) for v in (a, b)) or a < previous_word - .001 or a < start - .001 or not a < b <= end + .001:
                    raise ValueError("Invalid word alignment")
                previous_word = b
    if canonical(" ".join(s["text"] for s in segments)) != canonical(script.get("script", "")):
        raise ValueError("Full spoken script differs from aligned segments")
    return duration, segments


def caption_cues(segments):
    """Use measured word boundaries when available, otherwise sentence cues."""
    cues = []
    for segment in segments:
        words = segment.get("words", [])
        if not words:
            cues.append({"start": segment["start"], "end": segment["end"], "text": segment["text"], "timing": "measured_sentence", "words": []})
            continue
        group = []
        for word in words:
            text = " ".join(w["text"] for w in group + [word])
            if group and (len(group) >= 7 or len(text) > 48):
                cues.append({"start": group[0]["start"], "end": group[-1]["end"], "text": " ".join(w["text"] for w in group), "timing": "supplied_word_boundaries", "words": group})
                group = []
            group.append(word)
        if group:
            cues.append({"start": group[0]["start"], "end": group[-1]["end"], "text": " ".join(w["text"] for w in group), "timing": "supplied_word_boundaries", "words": group})
    return cues


def build_beats(script, edit, segments, duration):
    plans = edit.get("segments", [])
    if len(plans) != len(segments):
        raise ValueError("Edit needs exactly one plan per spoken segment")
    sources = {s["id"] for s in script.get("sources", [])}
    beats = []
    total = math.ceil(duration * FPS) / FPS
    for i, (segment, plan) in enumerate(zip(segments, plans)):
        if plan.get("id") != segment["id"] or plan.get("source") not in sources:
            raise ValueError("Edit refers to unknown script/evidence")
        titles = plan.get("title")
        if not isinstance(titles, list) or not 1 <= len(titles) <= 2 or any(not isinstance(line, str) or not line.strip() for line in titles):
            raise ValueError("Editorial titles require one or two nonempty lines")
        heading_size(titles)
        if not isinstance(plan.get("chapter"), str) or font(23, mono=True).getlength(plan["chapter"]) > 841:
            raise ValueError("Editorial chapter is wider than the portrait safe area")
        start = 0 if i == 0 else round(segment["start"] * FPS) / FPS
        end = round(segments[i + 1]["start"] * FPS) / FPS if i + 1 < len(segments) else total
        shots = plan.get("shots", [])
        if not shots or len(shots) > 3:
            raise ValueError("Each spoken segment needs one to three shots")
        for j, shot in enumerate(shots):
            a = start + round((end - start) * j / len(shots) * FPS) / FPS
            b = end if j + 1 == len(shots) else start + round((end - start) * (j + 1) / len(shots) * FPS) / FPS
            speed, source_start = shot.get("speed", 1), shot.get("source_start", 0)
            if not all(finite(v) for v in (speed, source_start)) or not .75 <= speed <= 1.25 or source_start < 0 or b <= a:
                raise ValueError("Invalid editorial shot timing")
            beats.append({**plan, **shot, "start": a, "end": b, "source_start": source_start, "speed": speed, "segment_start": start, "segment_end": end, "caption": segment["text"]})
    return beats, total


def lines_for(text, size=49, max_width=805, bold=True):
    lines, current = [], []
    for word in text.split():
        candidate = " ".join(current + [word])
        if current and font(size, bold=bold).getlength(candidate) > max_width:
            lines.append(current); current = [word]
        else:
            current.append(word)
    if current:
        lines.append(current)
    return lines


def panel(draw, box, alpha=226):
    draw.rounded_rectangle(box, radius=20, fill=(*INK, alpha), outline=(83, 109, 104, 170), width=1)


def evidence_graphic(draw, beat, t):
    mode = beat.get("graphic")
    p = min(1, max(0, (t - beat["segment_start"]) / 1.2))
    if not mode:
        return
    panel(draw, (84, 510, 920, 860))
    if mode == "sample":
        draw.text((116, 542), "RANDOMIZED TRIAL", font=font(24, mono=True), fill=MUTED)
        count = min(21, max(1, math.ceil(p * 21)))
        for n in range(21):
            x, y = 127 + (n % 7) * 58, 628 + (n // 7) * 58
            draw.ellipse((x, y, x + 27, y + 27), fill=TEAL if n < count else (44, 66, 63))
        draw.text((602, 590), "21", font=font(112, bold=True), fill=CHALK)
        draw.text((584, 729), "TRAINED MEN", font=font(25, mono=True), fill=CHALK)
    elif mode == "schedule":
        draw.text((116, 542), "SAME PLANNED TRAINING", font=font(25, mono=True), fill=MUTED)
        for n in range(8):
            x = 121 + n * 93
            draw.rounded_rectangle((x, 625, x + 65, 698), radius=8, fill=TEAL if n < math.ceil(p * 8) else (42, 59, 57))
            draw.text((x + 22, 646), str(n + 1), font=font(24, mono=True), fill=INK if n < math.ceil(p * 8) else MUTED)
        draw.text((118, 751), "8 WEEKS     3 SESSIONS / WEEK", font=font(30, mono=True), fill=CHALK)
    elif mode == "timers":
        draw.text((116, 542), "REST BETWEEN SETS", font=font(25, mono=True), fill=MUTED)
        for x, label, accent in ((270, "1:00", MUTED), (714, "3:00", COPPER)):
            draw.arc((x - 89, 605, x + 89, 783), -90, 270, fill=(54, 75, 71), width=7)
            draw.arc((x - 89, 605, x + 89, 783), -90, -90 + 360 * p, fill=accent, width=7)
            draw.text((x, 663), label, anchor="mt", font=font(47, mono=True), fill=CHALK)
        draw.text((469, 666), "vs", font=font(31), fill=MUTED)
    elif mode == "outcomes":
        draw.text((116, 542), "GREATER GAINS / 3-MIN GROUP", font=font(25, mono=True), fill=MUTED)
        for y, text in ((626, "BENCH-PRESS STRENGTH"), (714, "SQUAT STRENGTH")):
            draw.text((127, y), "+", font=font(47, bold=True), fill=TEAL)
            draw.text((192, y + 10), text, font=font(32, bold=True), fill=CHALK)
        draw.text((117, 809), "Direction only · not an effect-size chart", font=font(21), fill=MUTED)
    elif mode == "thigh":
        draw.text((116, 542), "MEASURED WITH ULTRASOUND", font=font(25, mono=True), fill=MUTED)
        draw.text((116, 624), "FRONT-OF-THIGH", font=font(46, bold=True), fill=CHALK)
        draw.text((116, 692), "MUSCLE THICKNESS", font=font(42, bold=True), fill=TEAL)
        draw.text((116, 787), "One measured site · not total muscle gained", font=font(25), fill=MUTED)
    elif mode == "limits":
        for x, number, label in ((119, "21", "MEN"), (395, "8", "WEEKS"), (655, "1", "TRIAL")):
            draw.text((x, 558), number, font=font(94, bold=True), fill=COPPER)
            draw.text((x, 694), label, font=font(28, mono=True), fill=CHALK)
        draw.text((118, 788), "Small sample. Limited generalizability.", font=font(29), fill=MUTED)
    elif mode == "review":
        draw.text((116, 542), "2024 SYSTEMATIC REVIEW", font=font(26, mono=True), fill=MUTED)
        for n in range(9):
            x = 121 + n * 81
            draw.rounded_rectangle((x, 624, x + 55, 696), radius=6, fill=TEAL if n < math.ceil(p * 9) else (42, 59, 57))
            draw.line((x + 12, 647, x + 42, 647), fill=INK, width=3)
            draw.line((x + 12, 659, x + 35, 659), fill=INK, width=3)
        draw.text((118, 750), "9 STUDIES.  UNCERTAINTY REMAINS.", font=font(29, mono=True), fill=CHALK)
    elif mode == "uncertainty":
        draw.text((116, 542), "WIDER EVIDENCE", font=font(26, mono=True), fill=MUTED)
        draw.text((116, 618), "SMALL POSSIBLE BENEFIT", font=font(42, bold=True), fill=TEAL)
        draw.text((116, 690), "Longer than 60 seconds", font=font(35), fill=CHALK)
        draw.text((116, 779), "Imprecise estimates · different protocols", font=font(27), fill=MUTED)
    elif mode == "no_magic":
        draw.text((116, 542), "NO UNIVERSAL WINNING TIMER", font=font(25, mono=True), fill=MUTED)
        draw.text((143, 625), "3:00", font=font(82, mono=True), fill=COPPER)
        draw.text((463, 640), "?", font=font(65, bold=True), fill=CHALK)
        draw.text((598, 625), "1:30", font=font(82, mono=True), fill=CHALK)
        draw.text((116, 785), "The review did not establish that rule.", font=font(28), fill=MUTED)


_SHADE = None


def narrated_overlay(beat, t, duration, source, cue):
    global _SHADE
    if _SHADE is None:
        y = np.arange(H, dtype=np.float32)
        opacity = np.maximum(np.clip((610 - y) / 480, 0, 1) * 196, np.clip((y - 1180) / 400, 0, 1) * 228).astype(np.uint8)
        rgba = np.zeros((H, W, 4), dtype=np.uint8); rgba[:, :, :3] = INK; rgba[:, :, 3] = opacity[:, None]
        _SHADE = Image.fromarray(rgba)
    layer = _SHADE.copy(); draw = ImageDraw.Draw(layer)
    draw.rectangle((84, 114, 92, 144), fill=COPPER)
    draw.text((112, 109), "REP SIGNAL", font=font(27, mono=True), fill=CHALK)
    draw.text((84, 179), beat["chapter"], font=font(23, mono=True), fill=MUTED)
    titles = beat["title"]
    size = heading_size(titles)
    rise = round(14 * (1 - min(1, (t - beat["segment_start"]) / .22)) ** 2)
    for i, line in enumerate(titles):
        draw.text((80, 242 + rise + i * (size + 10)), line, font=font(size, bold=True), fill=COPPER if i == beat.get("accent_line", 0) else CHALK)
    evidence_graphic(draw, beat, t)
    if cue:
        size = 49 if cue.get("words") else 43
        lines = lines_for(cue["text"], size=size)
        if len(lines) > 3:
            raise ValueError("Caption exceeds three portrait-safe lines")
        y = 1450 - (len(lines) - 1) * 27
        panel(draw, (68, y - 22, 941, y + len(lines) * 62 + 16), alpha=218)
        word_index = 0
        for line in lines:
            x = 96
            for word in line:
                color = CHALK
                if cue.get("words"):
                    item = cue["words"][word_index]
                    if item["start"] <= t < item["end"]:
                        color = COPPER
                draw.text((x, y), word, font=font(size, bold=True), fill=color)
                x += font(size, bold=True).getlength(word + " ")
                word_index += 1
            y += 62
    draw.text((84, 1650), source["display_citation"], font=font(25), fill=MUTED)
    draw.text((84, 1688), "doi:" + source["doi"], font=font(20, mono=True), fill=MUTED)
    draw.text((84, 1737), "Stock footage · not study participants", font=font(23), fill=MUTED)
    draw.text((84, 1781), "LOCAL REVIEW · SYNTHETIC NARRATION", font=font(20, mono=True), fill=MUTED)
    draw.line((84, 1834, 924, 1834), fill=(52, 70, 65), width=4)
    draw.line((84, 1834, 84 + round(840 * t / duration), 1834), fill=COPPER, width=4)
    return layer


def render_narrated(args):
    script = json.loads(args.brief.read_text()); edit = json.loads(args.edit.read_text())
    voice = json.loads(args.voice_provenance.read_text()); alignment = json.loads(args.alignment.read_text())
    if voice.get("rights_status") != "licensed" or not voice.get("license_url", "").startswith("https://") or voice.get("commercial_use_permitted") is not True or voice.get("synthetic") is not True:
        raise ValueError("Narrated neural review requires explicit commercial license/source evidence and synthetic disclosure")
    if not script.get("factual_caveat") or any(not s.get("url", "").startswith("https://") for s in script.get("sources", [])):
        raise ValueError("Narrated study requires sources and factual caveat")
    audio_duration, segments = validate_alignment(script, alignment, args.narration)
    beats, duration = build_beats(script, edit, segments, audio_duration)
    captions = caption_cues(segments)
    for cue in captions:
        if len(lines_for(cue["text"], size=49 if cue["words"] else 43)) > 3:
            raise ValueError("Spoken caption will not fit")
    provenance = json.loads(args.provenance.read_text())
    assets = verify_assets({"beats": beats}, provenance)
    font_files = [Path(font_path(bold=b, mono=m)) for b,m in ((False,False),(True,False),(False,True))]
    tracked = [args.brief, args.edit, args.voice_provenance, args.alignment, args.narration, args.provenance, Path(__file__), ROOT / "renderer/study.py", ROOT / "assets/licenses/DejaVu-LICENSE.txt", *font_files]
    hashes = {str(p.resolve()): sha256(p) for p in tracked}
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / ("." + output.stem + "-cache"); work.mkdir(exist_ok=True)
    bed, mixed = work / "original-soundbed.wav", work / "narrated-mix.wav"
    soundbed(bed, {"duration_seconds": duration, "beats": beats})
    # Original bed stays beneath the voice; normalize the final mix once.
    run(["ffmpeg", "-y", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", "wav", "-i", str(args.narration), "-i", str(bed), "-filter_complex", "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.0[v];[1:a]volume=0.21[b];[v][b]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=7[a]", "-map", "[a]", "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(mixed)])
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(mixed), "-t", str(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(output)]
    sources = {s["id"]: s for s in script["sources"]}
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for beat in beats:
            for index, frame in enumerate(decode_frames(assets[beat["shot"]], beat)):
                t = beat["start"] + index / FPS
                cue = next((c for c in captions if c["start"] <= t < c["end"]), None)
                layer = narrated_overlay(beat, t, duration, sources[beat["source"]], cue)
                frame = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
                encoder.stdin.write(frame.tobytes())
            print(f"Narrated edit {beat['end']:.2f}/{duration:.2f}s", flush=True)
    finally:
        encoder.stdin.close()
    error = encoder.stderr.read().decode(); encoder.stderr.close()
    if encoder.wait():
        raise RuntimeError(error)
    if any(sha256(Path(p)) != digest for p, digest in hashes.items()) or any(sha256(a["path"]) != a["sha256"] for a in assets.values()):
        output.unlink(missing_ok=True)
        raise ValueError("Source changed during rendering; review artifact discarded")
    output.with_suffix(".srt").write_text("\n\n".join(f"{i+1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i, c in enumerate(captions)) + "\n")
    manifest_assets = [{**{k:v for k,v in a.items() if k != "path"}, "kind":"visuals", "rights_status":"licensed", "provenance": a["usage"] + " Official asset page and Pexels License checked."} for a in assets.values()]
    manifest_assets.append({"kind":"visuals", "local_path":str(Path(__file__).resolve()), "sha256":sha256(Path(__file__)), "rights_status":"original", "provenance":"Original editorial typography, animated protocol/sample/review diagrams and caption composition authored for REP SIGNAL. No source paper figures or invented effect-size charts copied."})
    manifest_assets += [{"kind":"narration", "local_path":str(args.narration.resolve()), "sha256":sha256(args.narration), "rights_status":"licensed", "license_url":voice["license_url"], "provenance":voice}, {"kind":"sound_design", "local_path":str(bed), "sha256":sha256(bed), "rights_status":"original", "provenance":"Original deterministic percussion and tones authored in renderer/study.py; no borrowed music."}]
    for bold, mono in ((False, False), (True, False), (False, True)):
        p = Path(font_path(bold=bold, mono=mono))
        manifest_assets.append({"kind":"font", "local_path":str(p), "sha256":sha256(p), "rights_status":"licensed", "license_url":"https://dejavu-fonts.github.io/License.html", "license_file":"assets/licenses/DejaVu-LICENSE.txt", "provenance":"DejaVu Sans; bundled Bitstream Vera/DejaVu license permits document/video use."})
    manifest = {**script, "status":"LOCAL_REVIEW_SAMPLE", "duration_seconds":duration, "dimensions":[W,H], "fps":FPS, "human_approved":False, "publishable":False, "sha256":sha256(output), "audio_mode":"narrated", "narration_mode":"licensed_local_neural_voice", "narration":{**voice, "present":True, "human_recorded":False, "listening_review_status":"owner_review_required"}, "script_kind":"exact_spoken_script", "captions":captions, "beats":beats, "assets":manifest_assets, "input_sha256":hashes, "cost_usd":0, "stock_context":"Licensed stock athletes illustrate training; not study participants or endorsers.", "render_command":"python3 renderer/study.py --brief renderer/original-study-script.json --edit renderer/original-study-edit.json --narration <licensed.wav> --alignment <timings.json> --voice-provenance <license.json> --output output/review-2026-11-17/original-study.mp4"}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    qc = qc_video(output, duration); qc["audio_mode"] = "Licensed local neural narration with original sound design"; qc["publication_blockers"] = ["Owner review of exact video and voice pending", "No release approval", "Publishing disabled"]
    output.with_suffix(".qc.json").write_text(json.dumps(qc, indent=2) + "\n")
    sheet = Image.new("RGB", (864, 1152), INK)
    for i in range(12):
        at = (i + .5) * duration / 12
        path = work / f"actual-frame-{i}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(output), "-frames:v", "1", "-vf", "scale=216:384", str(path)])
        with Image.open(path) as still:
            sheet.paste(still, ((i % 4) * 216, (i // 4) * 384))
    sheet.save(output.with_suffix(".contact.jpg"), quality=95)
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.2", "-i", str(output), "-frames:v", "1", str(output.with_suffix(".poster.jpg"))])
    print(json.dumps({"video":str(output), "duration":duration, "technical_qc_passed":qc["passed"], "publishable":False}))
    if not qc["passed"]:
        raise SystemExit(2)
