"""Measured local media QC; editorial originality and delivery remain human reviewed."""
import json
import math
import re
import subprocess
from pathlib import Path


def inspect_media(path,captions):
    report={'passed':False,'checks':{'video':False,'audio':False,'duration':False,'resolution':False,'captions':False},'measurements':{},'errors':[],'inspector':'ffprobe+ffmpeg/v1'}
    if not path or not Path(path).is_file():
        report['errors'].append('Missing media file'); return report
    try:
        result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=45,check=True)
        probe=json.loads(result.stdout)
        video=next((s for s in probe.get('streams',[]) if s['codec_type']=='video'),{})
        audio=next((s for s in probe.get('streams',[]) if s['codec_type']=='audio'),{})
        duration=float(probe.get('format',{}).get('duration',0))
        numerator,denominator=map(int,video.get('avg_frame_rate','0/1').split('/'))
        fps=numerator/denominator if denominator else 0
        report['measurements']={'duration_seconds':duration,'width':video.get('width'),'height':video.get('height'),'fps':fps,'video_codec':video.get('codec_name'),'audio_codec':audio.get('codec_name')}
        report['checks']['video']=video.get('codec_name')=='h264' and 23<=fps<=61 and video.get('pix_fmt')=='yuv420p'
        report['checks']['resolution']=video.get('width')==1080 and video.get('height')==1920
        report['checks']['duration']=20<=duration<=90.5
        analysis=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,timeout=90)
        mean=re.search(r'mean_volume:\s*(-?[\d.]+) dB',analysis.stderr)
        peak=re.search(r'max_volume:\s*(-?[\d.]+) dB',analysis.stderr)
        mean_db=float(mean.group(1)) if mean else None; peak_db=float(peak.group(1)) if peak else None
        report['measurements'].update(mean_db=mean_db,peak_db=peak_db)
        report['checks']['audio']=audio.get('codec_name')=='aac' and analysis.returncode==0 and mean_db is not None and -45<mean_db<-5 and peak_db is not None and peak_db<0
        previous=0; caption_ok=bool(captions)
        for cue in captions:
            start=float(cue.get('start',cue.get('start_seconds',-1))); end=float(cue.get('end',cue.get('end_seconds',-1)))
            caption_ok=caption_ok and math.isfinite(start) and math.isfinite(end) and 0<=start<end<=duration+0.1 and start>=previous-0.03 and bool(str(cue.get('text','')).strip())
            previous=end
        report['checks']['captions']=bool(caption_ok)
        report['caption_scope']='Cue boundaries and text validated; readability and transcript accuracy require release review.'
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
        report['errors'].append(type(e).__name__+': '+str(e)[:240])
    return report
