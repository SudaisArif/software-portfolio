"""Import local rendered review packages without creating approvals or external requests.

The immutable MP4 and normalized provenance snapshot live under the database's
private review-artifacts directory. Source assets stay in place and are rehashed
at every promotion/release gate. Intake does not establish legal ownership.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from media_engine import GateError
from media_engine.engine import file_hash

ROOT=Path(__file__).resolve().parent
MAX_MEDIA_BYTES=200_000_000


def _https(value):
    if not isinstance(value,str):return False
    try:
        u=urlsplit(value)
        return u.scheme=='https' and bool(u.hostname) and not u.username and not u.password
    except ValueError:return False


def _local_path(value,root):
    if not isinstance(value,str) or not value:raise GateError('Every review asset needs a local path.')
    path=Path(value)
    if not path.is_absolute():path=root/path
    path=path.resolve()
    if not path.is_relative_to(root) or not path.is_file():raise GateError('Review assets must be existing files inside the project.')
    return path


def normalize_manifest(raw,video,root=ROOT):
    root=Path(root).resolve(); video=Path(video).resolve()
    if not isinstance(raw,dict):raise GateError('Review manifest must be an object.')
    script=raw.get('script'); title=raw.get('title') or raw.get('headline') or 'Source clip for review'
    if not isinstance(script,str) or not script.strip() or len(script)>30000:raise GateError('Manifest needs the exact script, at most 30,000 characters.')
    sources=raw.get('sources') or ([{'url':raw['source_url'],'title':'Original source'}] if raw.get('source_url') else [])
    if not isinstance(sources,list) or not sources or len(sources)>30 or any(not isinstance(s,dict) or not _https(s.get('url')) for s in sources):raise GateError('Manifest needs valid HTTPS evidence sources.')
    captions=raw.get('captions')
    if not captions and isinstance(raw.get('beats'),list):
        captions=[{'start':b['start'],'end':b['end'],'text':' '.join(b['title'])+' '+b['caption'].replace('\n',' ')} for b in raw['beats']]
    if not isinstance(captions,list) or not captions:raise GateError('Manifest needs measured captions or timed visual-essay beats.')
    audio_mode=raw.get('audio_mode')
    if audio_mode not in {'narrated','visual_essay','source_audio'}:
        narration=raw.get('narration')
        if raw.get('narration_mode')=='none_intentional_visual_essay' or isinstance(narration,dict) and narration.get('present') is False:audio_mode='visual_essay'
        elif raw.get('narration_mode')=='original_human_source_audio' or 'clip' in raw.get('format',''):audio_mode='source_audio'
        else:audio_mode='narrated'
    assets=[]
    for item in raw.get('assets',[]):
        if not isinstance(item,dict):raise GateError('Invalid asset provenance.')
        local=item.get('local_path') or item.get('path')
        if not local:raise GateError('Each declared asset must include its original local path; do not silently drop assets.')
        path=_local_path(local,root); expected=item.get('sha256') or item.get('source_sha256')
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected) or file_hash(path)!=expected:raise GateError('Source asset hash does not match the rendered manifest.')
        status=item.get('rights_status','unknown')
        if status=='primary_source_free_stock_license_verified':status='licensed'
        if status not in {'original','licensed','public_domain','unknown','preview_only'}:status='unknown'
        license_url=item.get('license_url','')
        if license_url and not _https(license_url):raise GateError('Asset license evidence must be HTTPS without credentials.')
        provenance=item.get('provenance') or item.get('usage') or item.get('credit') or item.get('origin') or 'Rights evidence requires editorial review.'
        if not isinstance(provenance,str):provenance=json.dumps(provenance,sort_keys=True)
        assets.append({'kind':item.get('kind','visuals'),'path':str(path),'sha256':expected,'rights_status':status,'license_url':license_url,'provenance':provenance})
    # Compatibility with the earlier NASA review cut. Preview-only remains blocked.
    provenance=raw.get('provenance',{})
    if not assets and isinstance(provenance,dict) and provenance.get('source_path'):
        path=_local_path(provenance['source_path'],root)
        if file_hash(path)!=provenance.get('source_sha256'):raise GateError('Clip source hash changed.')
        for kind in ('visuals','narration'):
            assets.append({'kind':kind,'path':str(path),'sha256':file_hash(path),'rights_status':'preview_only','license_url':provenance.get('rights_guidelines_url',''),'provenance':provenance.get('local_preview_basis','Educational review only; commercial rights unresolved.')})
    # Legacy study sound-bed and font records are reconstructed only from the
    # known renderer's actual, hash-checked files. Missing evidence stays blocked.
    if audio_mode=='visual_essay' and not any(a['kind']=='sound_design' for a in assets):
        sound=raw.get('sound_design',{}); path=video.parent/('.'+video.stem+'-cache')/'original-soundbed.wav'
        if path.is_file() and file_hash(path)==sound.get('source_sha256'):
            assets.append({'kind':'sound_design','path':str(path),'sha256':file_hash(path),'rights_status':'original','license_url':'','provenance':sound.get('origin','Original deterministic sound design.')})
    legacy=raw.get('script_kind') in {'on_screen_visual_essay_text_not_spoken','official_source_caption_transcript'}
    if legacy and not any(a['kind']=='font' for a in assets):
        for name in ('DejaVuSans.ttf','DejaVuSans-Bold.ttf','DejaVuSansMono.ttf'):
            font=root/'assets/fonts'/name
            if font.is_file():assets.append({'kind':'font','path':str(font),'sha256':file_hash(font),'rights_status':'licensed','license_url':'https://dejavu-fonts.github.io/License.html','provenance':'Bundled DejaVu font used by the known study/editorial renderer.'})
    if not assets:raise GateError('No source asset provenance available for this preview.')
    # Preserve explicit global release restrictions even when individual source
    # licenses are present; e.g. identifiable speakers and third-party content.
    if raw.get('commercial_release_unresolved') is True or raw.get('rights_status')=='preview_only':
        for a in assets:
            if a['kind'] in {'visuals','narration'}:a['rights_status']='preview_only'
    return {'schema_version':1,'title':title,'script':script,'sources':sources,'captions':captions,'assets':assets,'audio_mode':audio_mode,
            'brief':raw.get('factual_caveat') or raw.get('source_caption') or 'Review the complete rendered video, source context, and rights evidence before release.',
            'original_manifest':raw,'human_approved':False,'publishable':False}


def _snapshot_bytes(path,content):
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes()!=content:raise GateError('Existing immutable review snapshot does not match.')
        return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:out.write(content);out.flush();os.fsync(out.fileno())


def import_review_artifact(engine,video_path,manifest_path=None,*,job_id=None,expected_revision=None,repository_root=ROOT):
    video=Path(video_path).resolve(); manifest=Path(manifest_path or video.with_suffix('.json')).resolve(); root=Path(repository_root).resolve()
    if engine.status()['kill_switch']:raise GateError('Emergency kill switch is on.')
    if not video.is_file() or video.suffix.lower()!='.mp4' or not 0<video.stat().st_size<=MAX_MEDIA_BYTES:raise GateError('Review video must be a nonempty MP4 under 200 MB.')
    if not manifest.is_file() or manifest.stat().st_size>2_000_000:raise GateError('Review manifest missing or exceeds 2 MB.')
    raw_bytes=manifest.read_bytes(); raw=json.loads(raw_bytes); actual=file_hash(video)
    claimed=raw.get('sha256') or raw.get('artifact_sha256')
    if claimed is not None and claimed!=actual:raise GateError('Rendered MP4 hash differs from its sidecar manifest.')
    normalized=normalize_manifest(raw,video,root)
    if job_id is not None:
        job=engine.get_job(job_id)
        if expected_revision is None or expected_revision!=job['revision']:raise GateError('Explicit current revision is required to attach to an existing job.')
        if job['script']!=normalized['script']:raise GateError('Artifact script does not exactly match the saved job revision.')
    normalized['artifact_sha256']=actual
    content=(json.dumps(normalized,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    manifest_sha=hashlib.sha256(content).hexdigest()
    folder=Path(engine.db_path).resolve().parent/'review-artifacts'/actual/manifest_sha
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    for parent in (folder,folder.parent,folder.parent.parent):os.chmod(parent,0o700)
    target=folder/'video.mp4'; snapshot=folder/'manifest.json'
    if not target.exists():
        descriptor,name=tempfile.mkstemp(prefix='.video-',dir=folder)
        try:
            with os.fdopen(descriptor,'wb') as out,video.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):out.write(chunk)
                out.flush();os.fsync(out.fileno())
            if file_hash(name)!=actual:raise GateError('Rendered video changed during snapshot.')
            # Link is atomic and never overwrites a concurrently imported package.
            try:os.link(name,target)
            except FileExistsError:pass
        finally:Path(name).unlink(missing_ok=True)
    if target.is_symlink() or file_hash(target)!=actual:raise GateError('Immutable video snapshot mismatch.')
    _snapshot_bytes(snapshot,content)
    preview=engine.register_preview(title=normalized['title'],script=normalized['script'],sources=normalized['sources'],brief=normalized['brief'],path=target,artifact_sha256=actual,manifest_path=snapshot,manifest_sha256=manifest_sha,captions=normalized['captions'],assets=normalized['assets'],audio_mode=normalized['audio_mode'],job_id=job_id,expected_revision=expected_revision)
    report=engine.run_preview_qc(preview['id'])
    return {'job':engine.get_job(preview['job_id']),'preview':engine.get_preview(preview['id']),'qc':report,'publishable':False,'approval_created':False}
