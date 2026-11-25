#!/usr/bin/env python3
"""Render a short, full-bleed study edit from licensed local assets and speech.

Research/license evidence stays in the sidecar. This renderer has no publishing,
download, generation, account or approval operation.
"""
from __future__ import annotations

import argparse
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
    from .study import finite, sha256, verify_assets, decode_frames
else:
    from render import ROOT, W, H, FPS, SR, font, font_path, qc_video, run, srt_time
    from study import finite, sha256, verify_assets, decode_frames

WHITE = (255, 255, 250)
ACCENT = (221, 255, 88)
DARK = (7, 11, 9)


def canonical(text):
    return " ".join(text.split())


def aligned_speech(script, alignment, path):
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE" or audio.getnchannels() not in (1, 2):
            raise ValueError("Local narration must be PCM16 WAV")
        duration = audio.getnframes() / audio.getframerate()
    if not 30 <= duration <= 50:
        raise ValueError("Feed edit requires 30–50 seconds of speech")
    if alignment.get("audio_sha256") != sha256(path):
        raise ValueError("Speech/alignment hash mismatch")
    if not finite(alignment.get("duration_seconds")) or abs(alignment["duration_seconds"] - duration) > .05:
        raise ValueError("Speech/alignment duration mismatch")
    expected, segments = script.get("segments", []), alignment.get("segments", [])
    if not expected or len(expected) != len(segments):
        raise ValueError("Every script segment must be timed")
    cursor = 0
    for target, segment in zip(expected, segments):
        if segment.get("id") != target["id"] or canonical(segment.get("text", "")) != canonical(target["text"]):
            raise ValueError("Speech timing does not match the exact script")
        start, end = segment.get("start"), segment.get("end")
        if not all(finite(t) for t in (start, end)) or start < cursor - .001 or not start < end <= duration + .001:
            raise ValueError("Invalid sentence timing")
        cursor = end
        words = segment.get("words", [])
        if not words:
            if len(segment["text"].split()) > 5:
                raise ValueError(f"{segment['id']} needs word timing for short synced captions")
            continue
        if canonical(" ".join(word.get("text", "") for word in words)) != canonical(segment["text"]):
            raise ValueError("Word timing text differs from narration")
        previous = start
        for word in words:
            a, b = word.get("start"), word.get("end")
            if not all(finite(t) for t in (a, b)) or a < previous - .001 or a < start - .001 or not a < b <= end + .001:
                raise ValueError("Invalid word timing")
            previous = b
    if canonical(" ".join(s["text"] for s in segments)) != canonical(script.get("script", "")):
        raise ValueError("Full script differs from timed speech")
    return duration, segments


def short_captions(segments, edit=None):
    """Keep short cues on actual supplied word boundaries, without fake timing."""
    cues = []
    planned = {item['id']:item.get('caption_phrases') for item in (edit or {}).get('segments',[])}
    for segment in segments:
        words = segment.get("words")
        if not words:
            cues.append({"start":segment["start"], "end":segment["end"], "text":segment["text"], "words":[], "timing":"measured_segment"})
            continue
        phrases = planned.get(segment['id'])
        if phrases is not None:
            if not isinstance(phrases,list) or not phrases or any(not isinstance(p,str) or not 2<=len(p.split())<=5 for p in phrases):
                raise ValueError('Editorial caption phrases must contain 2–5 words')
            if canonical(' '.join(phrases)) != canonical(segment['text']):
                raise ValueError('Editorial caption phrases must preserve exact spoken text')
            groups=[];offset=0
            for phrase in phrases:
                n=len(phrase.split());group=words[offset:offset+n]
                if canonical(' '.join(word['text'] for word in group)) != canonical(phrase):
                    raise ValueError('Editorial caption words differ from measured timing')
                groups.append(group);offset+=n
            for group in groups:
                cues.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(word['text'] for word in group),'words':group,'timing':'supplied_word_boundaries'})
            continue
        groups, group = [], []
        for word in words:
            group.append(word)
            text = " ".join(w["text"] for w in group)
            if len(group) == 4 or (len(group) >= 2 and (len(text) > 22 or word["text"].endswith((".", "?", "!", ",", ";")))):
                groups.append(group); group = []
        if group:
            if len(group) == 1 and groups and len(groups[-1]) < 5:
                groups[-1].extend(group)
            else:
                groups.append(group)
        for group in groups:
            cues.append({"start":group[0]["start"], "end":group[-1]["end"], "text":" ".join(w["text"] for w in group), "words":group, "timing":"supplied_word_boundaries"})
    return cues


def build_shots(edit, segments, duration):
    plans = edit.get("segments", [])
    if len(plans) != len(segments):
        raise ValueError("Edit plans must match spoken segments")
    beats = []
    hold = edit.get("closing_hold_seconds", .65)
    if not finite(hold) or not 0 <= hold <= 1:
        raise ValueError("Closing hold must be at most one second")
    end_of_film = math.ceil((duration + hold) * FPS) / FPS
    for index, (plan, spoken) in enumerate(zip(plans, segments)):
        if plan.get("id") != spoken["id"]:
            raise ValueError("Edit/segment ID mismatch")
        a = 0 if index == 0 else round(spoken["start"] * FPS) / FPS
        b = end_of_film if index + 1 == len(segments) else round(segments[index + 1]["start"] * FPS) / FPS
        shots = plan.get("shots", [])
        if not 1 <= len(shots) <= 5:
            raise ValueError("Each segment needs 1–5 shot plans")
        for j, shot in enumerate(shots):
            start = a + round((b - a) * j / len(shots) * FPS) / FPS
            end = b if j + 1 == len(shots) else a + round((b - a) * (j + 1) / len(shots) * FPS) / FPS
            speed, source_start = shot.get("speed", 1), shot.get("source_start", 0)
            zoom_a, zoom_b = shot.get("zoom_start", 1), shot.get("zoom_end", 1.06)
            if not all(finite(x) for x in (speed, source_start, zoom_a, zoom_b)) or not .8 <= speed <= 1.25 or source_start < 0 or not 1 <= zoom_a <= 1.18 or not 1 <= zoom_b <= 1.18 or end <= start:
                raise ValueError("Invalid shot interval, speed or punch-in")
            if shot.get('right_shot'):
                right_start,right_speed=shot.get('right_source_start',0),shot.get('right_speed',1)
                if not all(finite(x) for x in (right_start,right_speed)) or right_start<0 or not .8<=right_speed<=1.25:
                    raise ValueError('Invalid comparison source interval')
            beats.append({**shot, "id":plan["id"], "start":start, "end":end, "segment_start":a, "segment_end":b, "source_start":source_start, "speed":speed, "zoom_start":zoom_a, "zoom_end":zoom_b, "graphic":shot.get("graphic",plan.get("graphic"))})
    return beats, end_of_film


def words_layout(text, size, width=855):
    lines, line = [], []
    for word in text.split():
        if line and font(size, bold=True).getlength(" ".join(line + [word]).upper()) > width:
            lines.append(line); line = [word]
        else:
            line.append(word)
    if line:
        lines.append(line)
    return lines


def caption_size(text):
    for size in range(91, 60, -2):
        lines = words_layout(text, size)
        if len(lines) <= 2 and all(font(size, bold=True).getlength(" ".join(line).upper()) <= 855 for line in lines):
            return size
    raise ValueError("Short caption does not fit the safe area")


def outlined(draw, xy, text, size, color=WHITE, anchor=None, stroke=7):
    draw.text(xy, text, font=font(size, bold=True), fill=color, stroke_width=stroke, stroke_fill=(*DARK, 245), anchor=anchor)


def overlay(beat, t, duration, hook, cue):
    layer = Image.new("RGBA", (W,H), (0,0,0,0)); draw = ImageDraw.Draw(layer)
    # The only persistent identity is this small mark. No technical/review text.
    draw.text((76, 100), "REP SIGNAL", font=font(23, bold=True), fill=(255,255,250,175), stroke_width=1, stroke_fill=(0,0,0,100))
    if t < 2.45:
        entrance = 1 + .035 * max(0, 1 - t / .16)
        size = min(128, int(118 * entrance))
        while max(font(size,bold=True).getlength(line) for line in hook) > 880:
            size -= 2
        for index, line in enumerate(hook):
            outlined(draw, (W/2, 302 + index * (size + 10)), line, size, ACCENT if index == len(hook)-1 else WHITE, anchor="mt", stroke=8)
    graphic = beat.get("graphic")
    if graphic == "timers":
        # Only protocol labels, no invented effect sizes or success scores.
        for x, value, color in ((267,"1:00",WHITE),(813,"3:00",ACCENT)):
            outlined(draw,(x,365),value,122,color,anchor="mt",stroke=8)
            outlined(draw,(x,520),"REST",39,WHITE,anchor="mt",stroke=4)
        outlined(draw,(540,437),"vs",48,WHITE,anchor="mt",stroke=5)
    elif graphic == "result":
        outlined(draw,(540,280),"LONGER REST",72,ACCENT,anchor="mt",stroke=6)
    elif graphic == "question":
        outlined(draw,(540,300),"TIME + LIFT?",94,ACCENT,anchor="mt",stroke=7)
    if cue:
        size = caption_size(cue["text"])
        lines = words_layout(cue["text"],size)
        y = 1350 - (len(lines)-1) * 49
        offset = 0
        for line in lines:
            line_width = font(size,bold=True).getlength(" ".join(line).upper())
            x = (W-line_width)/2
            for word in line:
                color = WHITE
                if cue["words"]:
                    timing = cue["words"][offset]
                    if timing["start"] <= t < timing["end"]:
                        color = ACCENT
                outlined(draw,(x,y),word.upper(),size,color,stroke=7)
                x += font(size,bold=True).getlength(word.upper()+" ")
                offset += 1
            y += size + 12
    return layer


def punch(frame, beat, t):
    p = (t-beat["start"])/(beat["end"]-beat["start"])
    z = beat["zoom_start"] + (beat["zoom_end"]-beat["zoom_start"]) * p
    if z <= 1.001:
        return frame
    width, height = W/z, H/z
    center_x, center_y = beat.get("focus_x",.5)*W, beat.get("focus_y",.5)*H
    left = min(W-width,max(0,center_x-width/2)); top = min(H-height,max(0,center_y-height/2))
    return frame.crop((round(left),round(top),round(left+width),round(top+height))).resize((W,H),Image.Resampling.BICUBIC)


def split_beat(beat):
    return {**beat,"shot":beat["right_shot"],"source_start":beat.get("right_source_start",0),"speed":beat.get("right_speed",1)}


def frames_for(assets, beat):
    if not beat.get("right_shot"):
        yield from decode_frames(assets[beat["shot"]],beat)
        return
    right = split_beat(beat)
    for left_frame,right_frame in zip(decode_frames(assets[beat["shot"]],beat),decode_frames(assets[right["shot"]],right)):
        frame = Image.new('RGB',(W,H))
        left_x = round(max(0,min(W/2,beat.get('left_focus_x',.65)*W-W/4)))
        right_x = round(max(0,min(W/2,beat.get('right_focus_x',.65)*W-W/4)))
        frame.paste(left_frame.crop((left_x,0,left_x+W//2,H)),(0,0))
        frame.paste(right_frame.crop((right_x,0,right_x+W//2,H)),(W//2,0))
        ImageDraw.Draw(frame).line((W//2,0,W//2,H),fill=WHITE,width=5)
        yield frame


def original_audio(path, duration, beats):
    """A new original pulse/texture bed; no external track or source audio."""
    count = round(duration*SR); t = np.arange(count,dtype=np.float32)/SR
    rng = np.random.default_rng(118)
    mono = np.zeros(count,dtype=np.float32)
    beat_length = 60/112
    # Sparse low notes and light percussion leave the narration upfront.
    for index, at in enumerate(np.arange(0,duration,beat_length)):
        start=round(at*SR); n=min(round(.30*SR),count-start); local=np.arange(n)/SR
        freq=(55,55,65.406,49)[(index//4)%4]
        mono[start:start+n] += .055*np.sin(2*np.pi*freq*local)*np.exp(-local*12)
        mono[start:start+n] += .045*np.sin(2*np.pi*(43*local+2*(1-np.exp(-30*local))))*np.exp(-local*24)
        if index%2:
            noise=rng.normal(0,1,n); mono[start:start+n] += .006*noise*np.exp(-local*90)
    for shot in beats:
        start=round(shot['start']*SR); n=min(round(.065*SR),count-start)
        mono[start:start+n] += .009*rng.normal(0,1,n)*np.exp(-np.arange(n)/(SR*.011))
    mono *= np.minimum(np.clip(t/.02,0,1),np.clip((duration-t)/.45,0,1))
    stereo=np.stack([mono,mono],axis=1)
    with wave.open(str(path),'wb') as audio:
        audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(SR);audio.writeframes((np.clip(stereo,-1,1)*32767).astype('<i2').tobytes())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('script','edit','narration','alignment','voice-provenance','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--provenance',type=Path,default=ROOT/'assets/footage/provenance.json')
    args=parser.parse_args(argv)
    script=json.loads(args.script.read_text());edit=json.loads(args.edit.read_text());alignment=json.loads(args.alignment.read_text());voice=json.loads(args.voice_provenance.read_text())
    if voice.get('rights_status')!='licensed' or voice.get('commercial_use_permitted') is not True or voice.get('synthetic') is not True or not voice.get('license_url','').startswith('https://'):
        raise ValueError('Documented licensed local narration is required')
    if not script.get('sources') or not script.get('factual_caveat'):
        raise ValueError('Internal evidence and factual limits are required')
    raw_duration,segments=aligned_speech(script,alignment,args.narration)
    beats,duration=build_shots(edit,segments,raw_duration);cues=short_captions(segments,edit)
    if canonical(' '.join(c['text'] for c in cues)) != canonical(script['script']):
        raise ValueError('Caption export must preserve every spoken word')
    for cue in cues:
        caption_size(cue['text'])
    hook=edit.get('opening_hook',[])
    if not isinstance(hook,list) or not 1<=len(hook)<=2 or any(not isinstance(line,str) or not line.strip() for line in hook):
        raise ValueError('Opening hook needs one or two short lines')
    provenance=json.loads(args.provenance.read_text())
    source_intervals=beats+[split_beat(beat) for beat in beats if beat.get('right_shot')]
    assets=verify_assets({'beats':source_intervals},provenance)
    fonts=[Path(font_path(bold=True))]
    inputs=[args.script,args.edit,args.narration,args.alignment,args.voice_provenance,args.provenance,Path(__file__),*fonts]
    hashes={str(path.resolve()):sha256(path) for path in inputs}
    output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True);work=output.parent/('.'+output.stem+'-cache');work.mkdir(exist_ok=True)
    bed,mix=work/'original-pulse.wav',work/'voice-mix.wav';original_audio(bed,duration,beats)
    run(['ffmpeg','-y','-v','error','-protocol_whitelist','file,pipe','-format_whitelist','wav','-i',str(args.narration),'-i',str(bed),'-filter_complex','[0:a]aformat=sample_rates=48000:channel_layouts=stereo[v];[1:a]volume=0.45[b];[v][b]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-15.5:TP=-1.5:LRA=7[a]','-map','[a]','-ar',str(SR),'-ac','2','-c:a','pcm_s16le',str(mix)])
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-i',str(mix),'-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar',str(SR),'-movflags','+faststart',str(output)]
    encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for beat in beats:
            for index,raw in enumerate(frames_for(assets,beat)):
                t=beat['start']+index/FPS
                frame=punch(raw,beat,t)
                cue=next((c for c in cues if c['start']<=t<c['end']),None)
                frame=Image.alpha_composite(frame.convert('RGBA'),overlay(beat,t,duration,hook,cue)).convert('RGB')
                encoder.stdin.write(frame.tobytes())
            print(f"Feed edit {beat['end']:.2f}/{duration:.2f}s",flush=True)
    finally:
        encoder.stdin.close()
    error=encoder.stderr.read().decode();encoder.stderr.close()
    if encoder.wait():raise RuntimeError(error)
    if any(sha256(Path(p))!=h for p,h in hashes.items()) or any(sha256(a['path'])!=a['sha256'] for a in assets.values()):
        output.unlink(missing_ok=True);raise ValueError('Render source changed; artifact discarded')
    output.with_suffix('.srt').write_text('\n\n'.join(f"{i+1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i,c in enumerate(cues))+'\n')
    manifest_assets=[{**{k:v for k,v in a.items() if k!='path'},'kind':'visuals','rights_status':'licensed','provenance':a['usage']} for a in assets.values()]
    manifest_assets.extend([{'kind':'visuals','local_path':str(Path(__file__).resolve()),'sha256':sha256(Path(__file__)),'rights_status':'original','provenance':'Original kinetic typography, editorial cut and protocol labels.'},{'kind':'narration','local_path':str(args.narration.resolve()),'sha256':sha256(args.narration),'rights_status':'licensed','license_url':voice['license_url'],'provenance':voice},{'kind':'sound_design','local_path':str(bed),'sha256':sha256(bed),'rights_status':'original','provenance':'Original authored pulse/percussion; no borrowed music.'},{'kind':'font','local_path':str(fonts[0]),'sha256':sha256(fonts[0]),'rights_status':'licensed','license_url':'https://dejavu-fonts.github.io/License.html','license_file':'assets/licenses/DejaVu-LICENSE.txt','provenance':'DejaVu Sans Bold under bundled Bitstream Vera/DejaVu terms.'}])
    manifest={**script,'status':'LOCAL_REVIEW_SAMPLE','publishable':False,'human_approved':False,'duration_seconds':duration,'dimensions':[W,H],'fps':FPS,'sha256':sha256(output),'script_kind':'exact_spoken_script','audio_mode':'narrated','narration_mode':'licensed_local_neural_voice','narration':{**voice,'human_recorded':False,'present':True},'captions':cues,'beats':beats,'assets':manifest_assets,'input_sha256':hashes,'public_overlay_policy':'Only hook, short synced speech captions, protocol comparison and minimal brand; no citation/paper/review/technical footers.','stock_context':'Licensed stock athletes illustrate the topic; not research participants or endorsers.','cost_usd':0}
    output.with_suffix('.json').write_text(json.dumps(manifest,indent=2)+'\n')
    qc=qc_video(output,duration);qc['publication_blockers']=['Owner review of rebuilt edit pending','Publication paused'];qc['audio_mode']='Licensed local neural narration and original pulse bed';output.with_suffix('.qc.json').write_text(json.dumps(qc,indent=2)+'\n')
    columns=5;rows=math.ceil(len(beats)/columns);sheet=Image.new('RGB',(216*columns,384*rows),DARK)
    for i,beat in enumerate(beats):
        at=(beat['start']+beat['end'])/2;path=work/f'frame-{i}.jpg'
        run(['ffmpeg','-y','-v','error','-ss',str(at),'-i',str(output),'-frames:v','1','-vf','scale=216:384',str(path)])
        with Image.open(path) as still:sheet.paste(still,((i%columns)*216,(i//columns)*384))
    sheet.save(output.with_suffix('.contact.jpg'),quality=95)
    run(['ffmpeg','-y','-v','error','-ss','0.5','-i',str(output),'-frames:v','1',str(output.with_suffix('.poster.jpg'))])
    print(json.dumps({'video':str(output),'duration':duration,'shots':len(beats),'captions':len(cues),'qc_passed':qc['passed'],'sha256':manifest['sha256'],'publishable':False}))
    if not qc['passed']:raise SystemExit(2)


if __name__=='__main__':main()
