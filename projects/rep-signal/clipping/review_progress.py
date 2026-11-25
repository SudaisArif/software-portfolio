"""Render the documented November 17 source-voice review cut; no external calls.

This editorial render preserves one continuous source passage. Source-captions
and offline ASR were compared; a person's final audiovisual approval is pending.
"""
from pathlib import Path
import hashlib
import json
import math
import subprocess
import textwrap
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/review-2026-11-17/clip-progress-proof-v2.mp4'
SOURCE=ROOT/'assets/footage/dvids-h2f-interviews.mp4'
EVIDENCE=ROOT/'assets/rights/review-2026-11-17'
URL='https://www.dvidshub.net/video/961171/creating-unit-organic-h2f-program-interviews'
LICENSE='https://www.dvidshub.net/about/copyright'
START,END,TAIL=18.62,62.72,4.0
W,H=1080,1920
BG='#101817';CREAM='#f2efe5';ORANGE='#e6a075';MUTED='#b4bfb6'
FONT=ROOT/'assets/fonts'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def font(size,bold=False):return ImageFont.truetype(str(FONT/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')),size)

def centered(draw,text,y,size=48,color=CREAM,bold=False):
    f=font(size,bold);width=draw.textlength(text,font=f)
    if width>960:raise ValueError('Text exceeds safe width: '+text)
    draw.text(((W-width)/2,y),text,font=f,fill=color)

def cue_words():
    rows=json.loads((EVIDENCE/'clip-offline-asr.json').read_text())
    words=[w.copy() for row in rows for w in row['words'] if START<=w['start'] and w['end']<=END]
    for word in words:
        word['word']=word['word'].strip().replace('BODPA','Bod Pod')
    normalized=[]
    for word in words:
        if word['word'].startswith('-') and normalized:
            normalized[-1]['word']+=word['word'];normalized[-1]['end']=word['end']
        else:normalized.append(word)
    words=normalized
    for i,word in enumerate(words):
        if word['word']=='5' and i>0 and words[i-1]['word']=='Week':
            word['word']='five,'
            if i+1<len(words) and words[i+1]['word']=='will':words[i+1]['word']="we’ll"
    # Correct the named body-composition instrument; do not turn the planned
    # programme assessment into a reported study outcome.
    cues=[];chunk=[]
    for word in words:
        chunk.append(word)
        if len(chunk)>=6 or word['word'].endswith(('.',',','?')) and len(chunk)>=3:
            cues.append({'start':round(chunk[0]['start']-START,3),'end':round(chunk[-1]['end']-START,3),'text':' '.join(w['word'] for w in chunk),'speaker':'Capt. Chante K. Burnell, Ph.D.'});chunk=[]
    if chunk:cues.append({'start':round(chunk[0]['start']-START,3),'end':round(chunk[-1]['end']-START,3),'text':' '.join(w['word'] for w in chunk),'speaker':'Capt. Chante K. Burnell, Ph.D.'})
    return cues,' '.join(w['word'] for w in words)

def overlay(caption,t,tail=False):
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,300),fill=BG);d.rectangle((0,1070,W,H),fill=BG)
    d.text((66,45),'REP SIGNAL',font=font(27,True),fill=ORANGE)
    d.text((730,47),'FIELD NOTES / 01',font=font(22),fill=MUTED)
    centered(d,'STRONGER—',100,76,bold=True)
    centered(d,'OR JUST SWEATIER?',193,68,ORANGE,True)
    # These bars also keep shirt/unit marks outside the editorial presentation.
    d.rectangle((0,1000,W,1075),fill=(16,24,23,245))
    centered(d,'Capt. Chante K. Burnell, Ph.D.',1019,31,bold=True)
    for i,line in enumerate(textwrap.wrap(caption,30,break_long_words=False)):
        centered(d,line,1110+i*65,49,bold=True)
    phase=0 if t<14.7 else 1 if t<20.9 else 2
    labels=[('01','BASELINE'),('02','TRAIN'),('03','RETEST')]
    for i,(number,label) in enumerate(labels):
        x=66+i*322;active=(i==phase)
        d.rounded_rectangle((x,1365,x+302,1500),radius=15,fill=ORANGE if active else '#24312d')
        d.text((x+21,1384),number,font=font(23,True),fill=BG if active else MUTED)
        d.text((x+21,1431),label,font=font(28,True),fill=BG if active else CREAM)
    centered(d,'Same tests. Comparable conditions.',1542,33,bold=True)
    centered(d,'A programme assessment plan — not published results.',1595,23,MUTED)
    centered(d,'Source: U.S. Army / SSG Raquel Birk / DVIDS',1655,25,MUTED)
    disclaimer='The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.'
    for i,line in enumerate(textwrap.wrap(disclaimer,58)):
        centered(d,line,1710+i*33,25,MUTED)
    centered(d,'Edited educational excerpt • 5 May 2025 • Review draft',1843,23,MUTED)
    d.rectangle((66,1810,1014,1815),fill='#304139')
    d.rectangle((66,1810,66+948*min(1,t/(END-START)),1815),fill=ORANGE)
    if tail:
        d.rectangle((0,300,W,1635),fill=BG)
        centered(d,'THE TAKEAWAY',465,30,ORANGE,True)
        for i,line in enumerate(['Pick one repeatable test.','Record the conditions.','Compare like with like.']):
            centered(d,line,660+i*125,49,bold=True)
        centered(d,'Don’t mistake effort for evidence of progress.',1120,33,MUTED)
        centered(d,'REP SIGNAL EDITORIAL NOTE',1460,24,ORANGE,True)
    return im

def srt_time(t):
    n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'

def main():
    if OUT.exists():raise SystemExit('Use a new artifact filename instead of replacing reviewed media.')
    duration=END-START;total=duration+TAIL
    cues,spoken=cue_words();cache=OUT.parent/('.'+OUT.stem+'-cache');cache.mkdir(parents=True,exist_ok=True)
    points=sorted(set([0.,duration,total,14.7,20.9]+[c[k] for c in cues for k in ('start','end')]))
    lines=['ffconcat version 1.0'];last=None
    for i,(a,b) in enumerate(zip(points,points[1:])):
        caption=next((c['text'] for c in cues if c['start']<=a+0.001<c['end']), '')
        path=cache/f'{i:03}.png';overlay(caption,a,tail=a>=duration).save(path)
        lines.extend([f"file '{path}'",f'duration {b-a:.6f}']);last=path
    lines.append(f"file '{last}'");timeline=cache/'overlay.ffconcat';timeline.write_text('\n'.join(lines)+'\n')
    filters=f'[0:v]crop=700:700:150:250,scale=1080:1080,pad=1080:1920:0:300:color=0x101817,setsar=1,fps=30,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={TAIL}[base];[base][1:v]overlay=0:0:shortest=1[v]'
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(START),'-t',str(duration),'-i',str(SOURCE),'-f','concat','-safe','0','-i',str(timeline),'-filter_complex',filters,'-map','[v]','-map','0:a:0','-t',str(total),'-c:v','libx264','-preset','fast','-crf','21','-maxrate','6500k','-bufsize','13000k','-pix_fmt','yuv420p','-af',f'loudnorm=I=-16:TP=-1.5:LRA=9,apad=pad_dur={TAIL}','-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-movflags','+faststart',str(OUT)],check=True)
    rights={'source_url':URL,'source_sha256':sha(SOURCE),'rights_status':'public_domain','commercial_use_allowed':True,'adaptation_allowed':True,'source_audio_included':True,'third_party_elements_reviewed':True,'rights_holder':'U.S. Army; official federal employee production credited to SSG Raquel Birk','license_url':LICENSE,'attribution':'U.S. Army / SSG Raquel Birk / DVIDS','reviewed_by':'Codex primary-source and visual evidence review, 2026-11-17','owner_attestation':'No private owner attestation. Reliance on the original publisher’s public-domain designation and official commercial-use authorization; see documented scope.','usage_scope':'Factual educational editorial excerpt, including a monetized editorial channel. Not a paid advertisement, endorsement, testimonial, political promotion, merchandise or voice clone.','personality_rights':'No general model release is claimed. Both adults appear in an official published interview in their professional roles. This excerpt reports the speaker’s actual programme explanation; it does not imply personal or agency endorsement of REP SIGNAL. Any advertising/endorsement use needs separate review.','music_review':'Selected from a raw interview; original speech/room audio retained. No added soundtrack, licensed stock music credit or third-party inserted media in the selected passage. Final human audio review remains pending.','required_disclaimer':'The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.','evidence_files':['assets/rights/review-2026-11-17/clip-source.html','assets/rights/review-2026-11-17/dvids-reuse.html','assets/rights/review-2026-11-17/clip-rights-review.md']}
    evidence=[{'url':URL,'title':'Original published interview (3:11), 5 May 2025'},{'url':LICENSE,'title':'DVIDS copyright, commercial-use and non-endorsement terms'}]
    assets=[{'kind':kind,'local_path':str(SOURCE.relative_to(ROOT)),'sha256':sha(SOURCE),'rights_status':'public_domain','license_url':LICENSE,'provenance':rights['usage_scope']+' '+rights['personality_rights']} for kind in ('visuals','narration')]
    for name in ('DejaVuSans.ttf','DejaVuSans-Bold.ttf'):
        p=FONT/name;assets.append({'kind':'font','local_path':str(p.relative_to(ROOT)),'sha256':sha(p),'rights_status':'licensed','license_url':'https://dejavu-fonts.github.io/License.html','provenance':'Bundled DejaVu font; license retained in assets/licenses/DejaVu-LICENSE.txt.'})
    note='Pick one repeatable test. Record the conditions. Compare like with like.'
    manifest={'format':'licensed_source_clip_v1','title':'Stronger—or just sweatier?','brand':'REP SIGNAL','audio_mode':'source_audio','mode':'source_audio','narration_mode':'original_human_source_audio','script':spoken+' '+note,'spoken_script':spoken,'script_kind':'source_speech_and_original_on_screen_editorial_text','on_screen_hook':'Stronger—or just sweatier?','editorial_takeaway':note,'source_url':URL,'source_sha256':sha(SOURCE),'source_interval':{'start':START,'end':END},'duration_seconds':total,'captions':cues+[{'start':duration,'end':total,'text':note,'speaker':'REP SIGNAL on-screen editorial note; not spoken'}],'sources':evidence,'assets':assets,'rights':rights,'rights_status':'public_domain','source_caption':'Excerpt from Creating a unit-organic H2F Program Interviews, U.S. Army / SSG Raquel Birk, DVIDS, 5 May 2025, 00:18.62–01:02.72. Portrait crop, faithful captions, normalized source voice and separate REP SIGNAL text takeaway. '+rights['required_disclaimer'],'factual_caveat':'The speaker describes a planned programme assessment. No results are supplied, no training outcome is guaranteed, and this is not presented as a clinical trial. This continuous passage retains the body-composition assessments as well as strength/endurance testing. Full source and surrounding discussion remain linked.','source_context_before':'The goal is a local 5th Armored Brigade holistic training programme, beginning with its physical component.','source_context_after':'The speaker describes possible improvements including grouping by fitness/agility and working on movement technique.','caption_review':{'method':'Official source captions compared with offline faster-whisper base.en word timestamps. Proper noun Bod Pod normalized. Human final listen and caption approval pending.','human_verified':False,'normalizations':['Joined split pre-assessment tokens.','Rendered Week 5 will as Week five, we’ll from first-person context; audio unchanged.','Normalized Bod Pod proper noun.'],'asr_file':'assets/rights/review-2026-11-17/clip-offline-asr.json'},'sound_design':{'present':False,'added_music':False,'description':'Original source voice and room sound only; four-second silent text ending.'},'source_audio_processing':'Original voice retained; loudness normalized only; four-second silent editorial ending. No synthetic narration or background music added.','layout':'Static manually configured speaker crop; no face tracking. Bottom overlay covers shirt insignia; no source/agency logo is repurposed as REP SIGNAL branding.','human_approved':False,'publishable':False,'originality_review_required':True,'context_review_required':True,'technical_qc':{'portrait':True,'h264_aac':True},'sha256':sha(OUT)}
    OUT.with_suffix('.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (EVIDENCE/'clip-rights.json').write_text(json.dumps(rights,ensure_ascii=False,indent=2)+'\n')
    OUT.with_suffix('.srt').write_text('\n\n'.join(f"{i+1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i,c in enumerate(cues))+'\n')
    subprocess.run(['ffmpeg','-v','error','-ss','2','-i',str(OUT),'-frames:v','1','-y',str(OUT.with_suffix('.poster.jpg'))],check=True)
    print(json.dumps({'output':str(OUT),'bytes':OUT.stat().st_size,'seconds':total,'sha256':sha(OUT)}))

if __name__=='__main__':main()
