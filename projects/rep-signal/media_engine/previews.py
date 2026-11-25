"""Revision-bound review artifacts. Import/QC never creates an approval."""
import hashlib
import json
import math
from pathlib import Path
import uuid

PREVIEW_SCHEMA = '''
CREATE TABLE IF NOT EXISTS preview_artifacts(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),revision INTEGER NOT NULL,
 path TEXT NOT NULL,artifact_sha256 TEXT NOT NULL,manifest_path TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,
 script_sha256 TEXT NOT NULL,audio_mode TEXT NOT NULL,captions TEXT NOT NULL,assets TEXT NOT NULL,
 qc TEXT,created_at REAL NOT NULL,UNIQUE(job_id,revision,artifact_sha256,manifest_sha256));
CREATE INDEX IF NOT EXISTS preview_job ON preview_artifacts(job_id,revision);
'''
AUDIO_KINDS = {
    'narrated': {'visuals','narration','sound_design','font'},
    'visual_essay': {'visuals','sound_design','font'},
    'source_audio': {'visuals','narration','font'},
}

def script_hash(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()

def caption_binding(script,captions):
    return ' '.join(script.split()) == ' '.join(' '.join(c['text'] for c in captions).split())


def check_assets(assets,audio_mode):
    from .engine import GateError,file_hash
    if audio_mode not in AUDIO_KINDS: raise GateError('Unknown artifact audio mode.')
    missing=AUDIO_KINDS[audio_mode]-{a['kind'] for a in assets}
    if missing: raise GateError('Asset rights manifest is incomplete; missing '+', '.join(sorted(missing)))
    for asset in assets:
        if asset['rights_status'] not in {'original','licensed','public_domain'} or not asset['provenance']:
            raise GateError('Unclear asset rights: '+asset['kind'])
        if asset['rights_status'] in {'licensed','public_domain'} and not asset['license_url']:
            raise GateError('Missing license evidence for '+asset['kind'])
        if not Path(asset['path']).is_file() or file_hash(asset['path'])!=asset['sha256']:
            raise GateError('Asset missing or changed: '+asset['kind'])


class PreviewMixin:
    def _decode_preview(self,row):
        value=dict(row)
        for key in ('assets','captions','qc'): value[key]=json.loads(value[key]) if value[key] else None
        value['human_approved']=False  # Only the owning job carries approval records.
        value['publishable']=False
        return value
    def _previews(self,c,job_id):
        return [self._decode_preview(r) for r in c.execute('SELECT * FROM preview_artifacts WHERE job_id=? ORDER BY created_at DESC,id DESC',(job_id,))]
    def get_preview(self,preview_id):
        with self._connect() as c:
            row=c.execute('SELECT * FROM preview_artifacts WHERE id=?',(preview_id,)).fetchone()
            if row is None: raise KeyError(preview_id)
            return self._decode_preview(row)
    def register_preview(self,*,title,script,sources,brief,path,artifact_sha256,manifest_path,manifest_sha256,
                         captions,assets,audio_mode,job_id=None,expected_revision=None):
        from .engine import GateError,ConflictError,file_hash,dumps
        if not isinstance(script,str) or not script.strip() or not isinstance(title,str) or not title.strip(): raise GateError('Artifact title and exact script are required.')
        if audio_mode not in AUDIO_KINDS: raise GateError('Unknown artifact audio mode.')
        if not sources or any(not isinstance(s,dict) or not str(s.get('url','')).startswith('https://') for s in sources): raise GateError('Artifact requires sourced evidence.')
        if not isinstance(captions,list) or not captions or not caption_binding(script,captions): raise GateError('Caption text must exactly match the script, ignoring whitespace.')
        last=0
        for cue in captions:
            start,end=cue.get('start'),cue.get('end')
            if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in (start,end)) or not 0<=start<end<=90.5 or start<last-0.03:
                raise GateError('Preview caption timings are invalid.')
            last=end
        if not isinstance(assets,list) or not assets: raise GateError('Asset provenance records are required even for previews.')
        for asset in assets:
            if not isinstance(asset,dict) or any(not isinstance(asset.get(k),str) for k in ('kind','path','sha256','rights_status','license_url','provenance')): raise GateError('Malformed asset provenance record.')
            if not Path(asset['path']).is_file() or file_hash(asset['path'])!=asset['sha256']: raise GateError('Preview source asset missing or changed.')
        path=str(Path(path).resolve()); manifest_path=str(Path(manifest_path).resolve())
        if file_hash(path)!=artifact_sha256 or file_hash(manifest_path)!=manifest_sha256: raise GateError('Review artifact or manifest changed during intake.')
        with self._tx() as c:
            self._active(c)
            # Idempotency across repeated CLI imports: no second job for the same immutable package.
            if job_id is None:
                existing=c.execute('SELECT * FROM preview_artifacts WHERE artifact_sha256=? AND manifest_sha256=? ORDER BY created_at LIMIT 1',(artifact_sha256,manifest_sha256)).fetchone()
                if existing:
                    current=self._job(c,existing['job_id'])
                    if current['revision']==existing['revision'] and script_hash(current['script'])==existing['script_sha256']:
                        return self._decode_preview(existing)
                job_id=uuid.uuid4().hex
                c.execute('INSERT INTO jobs(id,title,concept,state,revision,script,sources,brief,audio_mode,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (job_id,title,'review-artifact:'+artifact_sha256,'HUMAN_REVIEW',1,script,dumps(sources),brief,audio_mode,self.clock(),self.clock()))
                self._event(c,job_id,'created_from_review_artifact')
                self._event(c,job_id,'human_review_requested',revision=1)
            job=self._job(c,job_id)
            if expected_revision is not None and expected_revision!=job['revision']: raise ConflictError('Script revision changed; reload before importing.')
            if job['state'] not in {'HUMAN_REVIEW','SCRIPTED','APPROVED','QC'}: raise GateError('Job cannot accept review artifacts in '+job['state'])
            if job['script']!=script: raise ConflictError('Artifact script does not exactly match the saved job revision.')
            if {s['url'] for s in json.loads(job['sources'])}!={s['url'] for s in sources}: raise ConflictError('Artifact sources differ from the reviewed job sources.')
            existing=c.execute('SELECT * FROM preview_artifacts WHERE job_id=? AND revision=? AND artifact_sha256=? AND manifest_sha256=?',(job_id,job['revision'],artifact_sha256,manifest_sha256)).fetchone()
            if existing: return self._decode_preview(existing)
            preview_id=uuid.uuid4().hex
            c.execute('INSERT INTO preview_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (preview_id,job_id,job['revision'],path,artifact_sha256,manifest_path,manifest_sha256,script_hash(script),audio_mode,dumps(captions),dumps(assets),None,self.clock()))
            self._event(c,job_id,'preview_attached',revision=job['revision'],preview_id=preview_id,artifact_sha256=artifact_sha256,approval_created=False)
        return self.get_preview(preview_id)
    def _verify_preview(self,preview,job):
        from .engine import GateError,ConflictError,file_hash
        if preview['revision']!=job['revision'] or preview['script_sha256']!=script_hash(job['script']): raise ConflictError('Preview belongs to an old script revision.')
        for path,expected in ((preview['path'],preview['artifact_sha256']),(preview['manifest_path'],preview['manifest_sha256'])):
            if not Path(path).is_file() or file_hash(path)!=expected: raise GateError('Preview artifact or manifest changed since import.')
        for asset in preview['assets']:
            if not Path(asset['path']).is_file() or file_hash(asset['path'])!=asset['sha256']: raise GateError('Preview source asset changed since import.')
    def run_preview_qc(self,preview_id):
        from .qc import inspect_media
        from .engine import GateError,dumps
        preview=self.get_preview(preview_id); job=self.get_job(preview['job_id']); self._verify_preview(preview,job)
        report=inspect_media(preview['path'],preview['captions'])
        blockers=[]
        try: check_assets(preview['assets'],preview['audio_mode']); rights=True
        except GateError as exc: rights=False; blockers.append(str(exc))
        report['checks']['rights']=rights
        report['checks']['script_binding']=caption_binding(job['script'],preview['captions'])
        report['technical_passed']=all(report['checks'].get(k) is True for k in ('video','audio','duration','resolution','captions','script_binding'))
        report['passed']=report['technical_passed'] and rights
        report.update(artifact_sha256=preview['artifact_sha256'],manifest_sha256=preview['manifest_sha256'],revision=preview['revision'],publishable=False,approval_created=False,rights_blockers=blockers)
        with self._tx() as c:
            self._verify_preview(preview,self._job(c,preview['job_id']))
            c.execute('UPDATE preview_artifacts SET qc=? WHERE id=?',(dumps(report),preview_id))
            self._event(c,preview['job_id'],'preview_qc_completed',preview_id=preview_id,technical_passed=report['technical_passed'],rights_passed=rights)
        return report
    def stage_preview(self,preview_id,*,revision,artifact_sha256):
        """Select already rendered media for final QC after human script approval.

        This is an import, not a render or a release decision. Unclear rights
        remain visible in QC and always prevent final release and scheduling.
        """
        from .engine import GateError,ConflictError,dumps
        with self._tx() as c:
            self._active(c)
            row=c.execute('SELECT * FROM preview_artifacts WHERE id=?',(preview_id,)).fetchone()
            if row is None: raise KeyError(preview_id)
            preview=self._decode_preview(row); job=self._job(c,preview['job_id'])
            self._approval(job)
            if job['state'] not in {'APPROVED','QC'}: raise GateError('Approve the current script before staging its video.')
            if revision!=job['revision'] or artifact_sha256!=preview['artifact_sha256']: raise ConflictError('Explicit current revision and exact artifact hash are required.')
            self._verify_preview(preview,job)
            q=preview['qc'] or {}
            if not q.get('technical_passed') or q.get('artifact_sha256')!=artifact_sha256 or q.get('manifest_sha256')!=preview['manifest_sha256']: raise GateError('Run passing technical preview QC before staging.')
            self._mutable(c,job)
            # Registered input rows are replaced only for this explicit artifact selection.
            c.execute('DELETE FROM assets WHERE job_id=?',(job['id'],))
            for asset in preview['assets']:
                c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,job['id'],asset['kind'],asset['path'],asset['rights_status'],asset['license_url'],asset['provenance'],asset['sha256']))
            self._change(c,job['id'],state='QC',audio_mode=preview['audio_mode'],active_preview_id=preview_id,render_path=preview['path'],artifact_sha256=artifact_sha256,captions=dumps(preview['captions']),qc=None,release_sha256=None,release_approved_by=None)
            self._event(c,job['id'],'review_artifact_staged',preview_id=preview_id,revision=revision,artifact_sha256=artifact_sha256,approval_created=False)
        report=self.run_qc(job['id'])
        return {'job':self.get_job(job['id']),'qc':report,'awaiting_release_review':True,'publishable':False}
