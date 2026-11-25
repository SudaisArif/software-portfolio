"""Create a local portrait review excerpt while preserving the licensed source audio."""
from __future__ import annotations
import json
import math
from pathlib import Path
import subprocess
import tempfile
import textwrap
from .core import ClipError, validate_candidate, validate_rights, file_hash, digest_json

ROOT=Path(__file__).resolve().parents[1]
W,H,FPS=1080,1920,30


def _probe(path):
    result=subprocess.run(["ffprobe","-v","error","-protocol_whitelist","file,pipe","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-show_streams","-show_format","-of","json",str(path)],check=True,capture_output=True,text=True,timeout=45)
    return json.loads(result.stdout)


def _srt_time(seconds):
    value=round(seconds*1000)
    return f"{value//3600000:02}:{value//60000%60:02}:{value//1000%60:02},{value%1000:03}"


def _overlay_bytes(caption,headline,attribution):
    from PIL import Image,ImageDraw,ImageFont
    font_folder=ROOT/"assets/fonts"
    bold=ImageFont.truetype(str(font_folder/"DejaVuSans-Bold.ttf"),50)
    normal=ImageFont.truetype(str(font_folder/"DejaVuSans.ttf"),43)
    small=ImageFont.truetype(str(font_folder/"DejaVuSansMono.ttf"),24)
    image=Image.new("RGBA",(W,H),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,W,265),fill=(16,19,19,255));draw.rectangle((0,1460,W,H),fill=(16,19,19,235))
    draw.text((85,70),"REP SIGNAL / SOURCE CLIP",font=small,fill=(199,116,81,255))
    headline_lines=textwrap.wrap(headline,30)
    if len(headline_lines)>2 or any(draw.textlength(line,font=bold)>W-170 for line in headline_lines):raise ClipError("Headline is too wide for the portrait frame")
    for index,line in enumerate(headline_lines):draw.text((85,125+index*62),line,font=bold,fill=(241,237,228,255))
    lines=textwrap.wrap(caption,40,break_long_words=False)
    if len(lines)>4 or any(draw.textlength(line,font=normal)>W-170 for line in lines):
        raise ClipError("Caption segment is too long for safe layout; split and verify source timestamps")
    for index,line in enumerate(lines):draw.text((85,1530+index*56),line,font=normal,fill=(241,237,228,255))
    for index,line in enumerate(textwrap.wrap("SOURCE: "+attribution,58)[:2]):draw.text((85,1795+index*30),line,font=small,fill=(170,177,168,255))
    draw.text((85,1880),"LOCAL REVIEW / NOT APPROVED FOR RELEASE",font=small,fill=(199,116,81,255))
    return image.tobytes()


def render_clip(source_path,transcript,candidate,rights,output,focus_x=.5,layout="contain",context_reviewed_by=""):
    """No API calls, synthetic narration or publishing. Returns a review artifact only.

    `context_reviewed_by` records an actual review if supplied; absence remains pending.
    Never manufacture this identity or the source-rights attestations.
    """
    selected=validate_candidate(transcript,candidate);validate_rights(rights,transcript)
    source=Path(source_path).resolve();out=Path(output).resolve()
    if not source.is_file() or file_hash(source)!=transcript["source_sha256"]:raise ClipError("Source media missing or changed")
    if any(path.exists() for path in (out,out.with_suffix(".json"),out.with_suffix(".srt"),out.with_suffix(".poster.jpg"))):raise ClipError("Output or sidecar already exists; use a new name so prior review artifacts remain intact")
    if out.suffix.lower()!=".mp4":raise ClipError("Output must be an MP4 path")
    if isinstance(focus_x,bool) or not isinstance(focus_x,(int,float)) or not math.isfinite(focus_x) or not 0<=focus_x<=1:raise ClipError("focus_x must be between zero and one")
    if layout not in {"contain","crop"}:raise ClipError("Layout must be contain or crop")
    if not isinstance(context_reviewed_by,str):raise ClipError("Context reviewer must be a real identity string or left empty")
    probe=_probe(source)
    if not any(s.get("codec_type")=="video" for s in probe.get("streams",[])):raise ClipError("Source has no video stream")
    if not any(s.get("codec_type")=="audio" for s in probe.get("streams",[])):raise ClipError("Source has no original audio stream; do not silently synthesize a replacement voice")
    source_duration=float(probe.get("format",{}).get("duration",0))
    if candidate["end"]>source_duration+.03:raise ClipError("Clip extends beyond source duration")
    duration=candidate["end"]-candidate["start"]
    if len(selected)>160:raise ClipError("Too many caption cues for one clip; combine and re-verify transcript timing")
    captions=[{"start":s["start"]-candidate["start"],"end":s["end"]-candidate["start"],"text":s["text"],"speaker":s["speaker"]} for s in selected]
    headline=candidate.get("headline","A training claim worth a closer look")
    if not isinstance(headline,str) or not headline.strip() or len(textwrap.wrap(headline,30))>2:raise ClipError("Headline must fit two short lines")
    # Validate every layout before encoding; retain just one frame to bound memory.
    for caption in captions:_overlay_bytes(caption["text"],headline,rights["attribution"])
    empty=_overlay_bytes("",headline,rights["attribution"])
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".clip-",dir=out.parent) as folder:
        temp=Path(folder)/"clip.mp4"
        resize="scale=1080:1200:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:280:color=0x101313"
        if layout=="crop":resize=f"scale=1080:1200:force_original_aspect_ratio=increase,crop=1080:1200:(in_w-out_w)*{focus_x}:(in_h-out_h)/2,pad=1080:1920:0:280:color=0x101313"
        filters=f"[0:v]{resize},setsar=1,fps={FPS},setpts=PTS-STARTPTS[base];[base][1:v]overlay=0:0:shortest=1[v]"
        args=["ffmpeg","-y","-v","error","-ss",str(candidate["start"]),"-t",str(duration),"-protocol_whitelist","file,pipe","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-i",str(source),
              "-f","rawvideo","-pix_fmt","rgba","-s",f"{W}x{H}","-r",str(FPS),"-i","-",
              "-filter_complex",filters,"-map","[v]","-map","0:a:0","-t",str(duration),
              "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
              "-af","loudnorm=I=-16:TP=-1.5:LRA=9","-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-movflags","+faststart",str(temp)]
        with (Path(folder)/"ffmpeg.log").open("wb") as errors:
            process=subprocess.Popen(args,stdin=subprocess.PIPE,stderr=errors)
            try:
                current_text="";current_overlay=empty
                for frame in range(math.ceil(duration*FPS)):
                    t=frame/FPS
                    cue=next((c for c in captions if c["start"]<=t<c["end"]),None)
                    cue_text=cue["text"] if cue else ""
                    if cue_text!=current_text:
                        current_text=cue_text
                        current_overlay=_overlay_bytes(cue_text,headline,rights["attribution"]) if cue_text else empty
                    process.stdin.write(current_overlay)
                process.stdin.close()
                if process.wait(timeout=90)!=0:raise ClipError("FFmpeg clipping failed; source may have an unsupported stream")
            except BaseException:
                if process.stdin and not process.stdin.closed:process.stdin.close()
                if process.poll() is None:process.terminate();process.wait(timeout=10)
                raise
        if file_hash(source)!=transcript["source_sha256"]:raise ClipError("Source changed while rendering; output rejected")
        info=_probe(temp)
        video=next(s for s in info["streams"] if s["codec_type"]=="video")
        audio=next(s for s in info["streams"] if s["codec_type"]=="audio")
        actual_duration=float(info["format"]["duration"])
        if (video["width"],video["height"],video["codec_name"],audio["codec_name"])!=(1080,1920,"h264","aac") or abs(actual_duration-duration)>.2:
            raise ClipError("Clipped video failed technical validation")
        temp.replace(out)
    out.with_suffix(".srt").write_text("\n\n".join(f"{index+1}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}" for index,c in enumerate(captions))+"\n")
    manifest={"format":"licensed_source_clip_v1","brand":"REP SIGNAL","source_url":transcript["source_url"],"source_sha256":transcript["source_sha256"],"transcript_sha256":digest_json(transcript),"candidate_id":candidate["candidate_id"],"source_interval":{"start":candidate["start"],"end":candidate["end"]},"duration_seconds":actual_duration,"script":candidate["text"],"captions":captions,"rights":rights,"layout":layout,"focus_x":focus_x if layout=="crop" else None,"camera_tracking":"none; crop position is explicitly configured","narration":"original source audio retained; loudness normalized","context_reviewed_by":context_reviewed_by or None,"context_review_required":not bool(context_reviewed_by.strip()),"originality_review_required":True,"human_approved":False,"publishable":False,"sha256":file_hash(out),"technical_qc":{"portrait":True,"h264_aac":True,"duration_matches":True},"source_caption":f"Excerpt: {rights['attribution']}. Source: {transcript['source_url']} at {candidate['start']:.2f}–{candidate['end']:.2f}s. {rights.get('license_url','Owned source')}. Edited to portrait; source audio retained. Claims require editorial review."}
    out.with_suffix(".json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    subprocess.run(["ffmpeg","-v","error","-ss","1","-i",str(out),"-frames:v","1","-y",str(out.with_suffix(".poster.jpg"))],check=True,capture_output=True,timeout=30)
    return manifest
