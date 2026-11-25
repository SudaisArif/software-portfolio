from __future__ import annotations
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .previews import PREVIEW_SCHEMA, PreviewMixin, check_assets
from .manual import MANUAL_SCHEMA, ManualDeliveryMixin

STATES = {'DISCOVERED','RESEARCHED','SCRIPTED','HUMAN_REVIEW','APPROVED','RENDERING','QC','SCHEDULED','PUBLISHED','ANALYZED','FAILED','RETRYING','CANCELLED'}
PLATFORMS = {'youtube','instagram','tiktok'}
QC_CHECKS = {'video','audio','duration','resolution','captions','rights','originality'}
REQUIRED_ASSET_KINDS = {'visuals','narration','sound_design','font'}
class _Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

class GateError(ValueError): pass
class ConflictError(GateError): pass
class RetryablePublishError(Exception):
    """Provider guarantees no item was accepted; retry is safe."""
class AmbiguousPublishError(Exception):
    """Submission may have been accepted. Manual reconciliation required."""

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY,title TEXT NOT NULL,concept TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,script TEXT NOT NULL DEFAULT '',sources TEXT NOT NULL DEFAULT '[]',brief TEXT NOT NULL DEFAULT '',
 approved_revision INTEGER,script_approved_by TEXT,render_path TEXT,artifact_sha256 TEXT,captions TEXT NOT NULL DEFAULT '[]',
 qc TEXT,release_sha256 TEXT,release_approved_by TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT,render_lease_until REAL,retry_at REAL,render_token TEXT);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),kind TEXT NOT NULL,path TEXT NOT NULL,
 rights_status TEXT NOT NULL,license_url TEXT NOT NULL,provenance TEXT NOT NULL,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,event TEXT NOT NULL,actor TEXT NOT NULL,payload TEXT NOT NULL,at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS renders(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,day TEXT NOT NULL,at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),revision INTEGER NOT NULL,
 platform TEXT NOT NULL,fingerprint TEXT NOT NULL,scheduled_at REAL NOT NULL,day TEXT NOT NULL,status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,lease_until REAL,retry_at REAL,external_id TEXT,url TEXT,error TEXT,account_id TEXT,
 UNIQUE(job_id,revision,platform),UNIQUE(platform,fingerprint));
CREATE TABLE IF NOT EXISTS reservations(job_id TEXT NOT NULL,revision INTEGER NOT NULL,day TEXT NOT NULL,PRIMARY KEY(job_id,revision,day));
CREATE TABLE IF NOT EXISTS costs(id TEXT PRIMARY KEY,provider TEXT NOT NULL,reserved REAL NOT NULL,actual REAL,status TEXT NOT NULL,month TEXT NOT NULL,at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS metrics(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,platform TEXT NOT NULL,external_id TEXT NOT NULL,
 observed_at REAL NOT NULL,source TEXT NOT NULL,values_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS delivery_due ON deliveries(status,scheduled_at,retry_at);
CREATE INDEX IF NOT EXISTS job_events ON events(job_id,at);
'''

def dumps(x): return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def file_hash(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def timestamp(value):
    if isinstance(value,(int,float)): return float(value)
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None: raise GateError('Schedule must include an explicit timezone offset.')
    return dt.timestamp()

class Engine(PreviewMixin, ManualDeliveryMixin):
    def __init__(self,db_path='data/media.db',clock=time.time):
        self.db_path=str(db_path); self.clock=clock
        Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as c:
            c.executescript(SCHEMA)
            c.executescript(PREVIEW_SCHEMA)
            columns={r[1] for r in c.execute('PRAGMA table_info(jobs)')}
            for column in ('render_lease_until','retry_at','render_token'):
                if column not in columns: c.execute('ALTER TABLE jobs ADD COLUMN '+column+(' TEXT' if column=='render_token' else ' REAL'))
            if 'audio_mode' not in columns: c.execute("ALTER TABLE jobs ADD COLUMN audio_mode TEXT NOT NULL DEFAULT 'narrated'")
            if 'active_preview_id' not in columns: c.execute('ALTER TABLE jobs ADD COLUMN active_preview_id TEXT')
            delivery_columns={r[1] for r in c.execute('PRAGMA table_info(deliveries)')}
            if 'account_id' not in delivery_columns: c.execute('ALTER TABLE deliveries ADD COLUMN account_id TEXT')
            if 'dispatch_mode' not in delivery_columns: c.execute("ALTER TABLE deliveries ADD COLUMN dispatch_mode TEXT NOT NULL DEFAULT 'api'")
            c.executescript(MANUAL_SCHEMA)
            for k,v in {'kill_switch':False,'publication_enabled':False,'daily_video_limit':1,'daily_render_limit':10,'monthly_ceiling':150.0,'approved_budget':0.0,'timezone':'Europe/London','platform_accounts':{}}.items():
                c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,dumps(v)))
        try: os.chmod(self.db_path,0o600)
        except OSError: pass
    def _connect(self):
        c=sqlite3.connect(self.db_path,timeout=20,factory=_Connection); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=20000')
        return c
    @contextlib.contextmanager
    def _tx(self):
        c=self._connect()
        try:
            c.execute('BEGIN IMMEDIATE'); yield c; c.commit()
        except BaseException: c.rollback(); raise
        finally: c.close()
    def _setting(self,c,key): return json.loads(c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0])
    def _set(self,c,key,value): c.execute('UPDATE settings SET value=? WHERE key=?',(dumps(value),key))
    def _event(self,c,job_id,event,actor='system',**payload):
        c.execute('INSERT INTO events(job_id,event,actor,payload,at) VALUES(?,?,?,?,?)',(job_id,event,actor,dumps(payload),self.clock()))
    def _job(self,c,job_id):
        row=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None: raise KeyError(job_id)
        return row
    def _change(self,c,job_id,**values):
        values['updated_at']=self.clock()
        c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),job_id))
    def _day(self,c,at): return datetime.fromtimestamp(at,ZoneInfo(self._setting(c,'timezone'))).strftime('%Y-%m-%d')
    def _month(self,c): return self._day(c,self.clock())[:7]
    def _active(self,c):
        if self._setting(c,'kill_switch'): raise GateError('Emergency kill switch is on.')
    def _mutable(self,c,j,allow_rendering=False):
        if j['state']=='RENDERING' and not allow_rendering: raise GateError('An active render must finish or be cancelled before changing its inputs.')
        outstanding=c.execute("SELECT 1 FROM deliveries WHERE job_id=? AND status IN ('IN_FLIGHT','SUBMITTED','UNKNOWN','PUBLISHED')",(j['id'],)).fetchone()
        if outstanding: raise GateError('Published or uncertain submissions are immutable; create a new job.')
        c.execute("DELETE FROM deliveries WHERE job_id=? AND status IN ('SCHEDULED','RETRYING','CANCELLED')",(j['id'],))
        c.execute('DELETE FROM reservations WHERE job_id=?',(j['id'],))
    def _approval(self,j):
        if j['approved_revision']!=j['revision'] or not j['script_approved_by']: raise GateError('Current script revision requires explicit human approval.')
    def _rights(self,c,job_id):
        assets=c.execute('SELECT * FROM assets WHERE job_id=?',(job_id,)).fetchall()
        if not assets: raise GateError('No asset rights manifest registered.')
        check_assets(assets,self._job(c,job_id)['audio_mode'])
    def _artifact(self,j):
        if not j['render_path'] or not Path(j['render_path']).is_file() or file_hash(j['render_path'])!=j['artifact_sha256']: raise GateError('Rendered artifact is missing or changed.')
        if j['active_preview_id']: self._verify_preview(self.get_preview(j['active_preview_id']),j)
    def _publish_gates(self,c,j):
        self._active(c); self._approval(j); self._rights(c,j['id']); self._artifact(j)
        q=json.loads(j['qc'] or '{}')
        if q.get('artifact_sha256')!=j['artifact_sha256'] or not q.get('passed') or not all(q.get('checks',{}).get(k) is True for k in QC_CHECKS): raise GateError('Current artifact has not passed every QC check.')
        if j['release_sha256']!=j['artifact_sha256'] or not j['release_approved_by']: raise GateError('Human release approval required for this exact artifact.')
    def _decode(self,row):
        d=dict(row)
        for k in ('sources','captions','qc'):
            if k in d: d[k]=json.loads(d[k]) if d[k] else None
        return d
    def create_job(self,title,concept='',sources=None):
        if not title.strip(): raise GateError('Title is required.')
        job_id=uuid.uuid4().hex
        with self._tx() as c:
            c.execute('INSERT INTO jobs(id,title,concept,state,sources,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(job_id,title,concept,'DISCOVERED',dumps(sources or []),self.clock(),self.clock()))
            self._event(c,job_id,'created')
        return self.get_job(job_id)
    def get_job(self,job_id):
        with self._connect() as c:
            d=self._decode(self._job(c,job_id)); d['assets']=[dict(r) for r in c.execute('SELECT * FROM assets WHERE job_id=?',(job_id,))]
            d['deliveries']=[dict(r) for r in c.execute('SELECT * FROM deliveries WHERE job_id=?',(job_id,))]
            d['previews']=self._previews(c,job_id)
            return d
    def list_jobs(self):
        with self._connect() as c:
            jobs=[self._decode(r) for r in c.execute('SELECT * FROM jobs ORDER BY created_at DESC')]
            for job in jobs: job['previews']=self._previews(c,job['id'])
            return jobs
    def list_assets(self,job_id): return self.get_job(job_id)['assets']
    def set_research(self,job_id,sources,brief):
        if not sources or any(not isinstance(s,dict) or not str(s.get('url','')).startswith('https://') for s in sources): raise GateError('Research requires source records with HTTPS URLs.')
        with self._tx() as c:
            j=self._job(c,job_id)
            if j['state'] not in {'DISCOVERED','RESEARCHED'}: raise GateError('Research is locked once a script enters review; create a revision with set_script.')
            self._change(c,job_id,sources=dumps(sources),brief=brief,state='RESEARCHED'); self._event(c,job_id,'researched',sources=len(sources))
        return self.get_job(job_id)
    def set_script(self,job_id,script,submit=True,expected_revision=None):
        if not isinstance(script,str) or not script.strip(): raise GateError('Script is empty.')
        with self._tx() as c:
            j=self._job(c,job_id)
            if expected_revision is not None and expected_revision!=j['revision']: raise ConflictError('Script revision changed; reload before editing.')
            self._mutable(c,j)
            if not json.loads(j['sources']): raise GateError('A sourced brief is required before script review.')
            self._change(c,job_id,script=script,active_preview_id=None,revision=j['revision']+1,state='HUMAN_REVIEW' if submit else 'SCRIPTED',approved_revision=None,script_approved_by=None,render_path=None,artifact_sha256=None,captions='[]',qc=None,release_sha256=None,release_approved_by=None,error=None)
            self._event(c,job_id,'scripted',revision=j['revision']+1)
            if submit: self._event(c,job_id,'human_review_requested',revision=j['revision']+1)
        return self.get_job(job_id)
    def submit_review(self,job_id):
        with self._tx() as c:
            j=self._job(c,job_id)
            if j['state']!='SCRIPTED': raise GateError('Only a saved draft can enter review.')
            self._change(c,job_id,state='HUMAN_REVIEW'); self._event(c,job_id,'human_review_requested',revision=j['revision'])
        return self.get_job(job_id)
    def review_script(self,job_id,decision,actor='human',revision=None,feedback=''):
        if decision not in {'approve','reject','revise'}: raise GateError('Decision must be approve, reject or revise.')
        if not actor.strip(): raise GateError('Human reviewer identity is required.')
        with self._tx() as c:
            j=self._job(c,job_id)
            if revision is None or revision!=j['revision']: raise ConflictError('Explicit current revision is required.')
            if j['state']!='HUMAN_REVIEW': raise GateError('Job is not awaiting script review.')
            values={'state':{'approve':'APPROVED','reject':'CANCELLED','revise':'HUMAN_REVIEW'}[decision]}
            if decision=='approve': values.update(approved_revision=revision,script_approved_by=actor)
            self._change(c,job_id,**values); self._event(c,job_id,'script_'+decision,actor,revision=revision,feedback=feedback)
        return self.get_job(job_id)
    def add_asset(self,job_id,kind,path,rights_status,license_url='',provenance=''):
        path=str(Path(path).resolve())
        if not Path(path).is_file(): raise GateError('Asset must be an existing local file.')
        if rights_status not in {'original','licensed','public_domain','unknown','preview_only'}: raise GateError('Invalid rights status.')
        asset_id=uuid.uuid4().hex
        with self._tx() as c:
            j=self._job(c,job_id); self._mutable(c,j)
            c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)',(asset_id,job_id,kind,path,rights_status,license_url,provenance,file_hash(path)))
            self._change(c,job_id,qc=None,release_sha256=None,release_approved_by=None,state='APPROVED' if j['approved_revision']==j['revision'] else j['state'])
            self._event(c,job_id,'asset_registered',asset_id=asset_id,rights_status=rights_status)
        return asset_id
    def start_render(self,job_id):
        with self._tx() as c:
            self._active(c); j=self._job(c,job_id); self._mutable(c,j); self._approval(j); self._rights(c,job_id)
            if j['state'] not in {'APPROVED','RETRYING','FAILED','QC'}: raise GateError('Cannot begin rendering in '+j['state'])
            if j['retry_at'] is not None and j['retry_at']>self.clock(): raise GateError('Render retry backoff has not elapsed.')
            day=self._day(c,self.clock())
            if c.execute('SELECT count(*) FROM renders WHERE day=?',(day,)).fetchone()[0]>=self._setting(c,'daily_render_limit'): raise GateError('Daily render limit reached.')
            c.execute('INSERT INTO renders VALUES(?,?,?,?)',(uuid.uuid4().hex,job_id,day,self.clock()))
            self._change(c,job_id,state='RENDERING',active_preview_id=None,render_token=uuid.uuid4().hex,render_lease_until=self.clock()+900,retry_at=None,render_path=None,artifact_sha256=None,qc=None,release_sha256=None,release_approved_by=None,error=None); self._event(c,job_id,'render_started')
        return self.get_job(job_id)
    def render_heartbeat(self,job_id,*,render_token):
        with self._tx() as c:
            self._active(c); j=self._job(c,job_id)
            if j['state']!='RENDERING': raise GateError('Job is not rendering.')
            if not render_token or j['render_token']!=render_token: raise ConflictError('Render lease token is stale.')
            self._change(c,job_id,render_lease_until=self.clock()+900)
    def fail_render(self,job_id,retryable=True,*,render_token):
        with self._tx() as c:
            j=self._job(c,job_id)
            if j['state']!='RENDERING': raise GateError('Job is not rendering.')
            if not render_token or j['render_token']!=render_token: raise ConflictError('Render lease token is stale.')
            self._change(c,job_id,state='RETRYING' if retryable else 'FAILED',render_lease_until=None,retry_at=self.clock()+60 if retryable else None,error='Rendering failed; inspect worker logs.')
            self._event(c,job_id,'render_failed',retryable=bool(retryable))
    def finish_render(self,job_id,path,captions=None,*,revision,render_token):
        path=str(Path(path).resolve()); sha=file_hash(path)
        with self._tx() as c:
            self._active(c); j=self._job(c,job_id); self._approval(j)
            if j['state']!='RENDERING': raise GateError('Job is not rendering.')
            if not render_token or j['render_token']!=render_token: raise ConflictError('Render lease token is stale.')
            if revision!=j['revision']: raise ConflictError('Rendered script revision is stale.')
            self._rights(c,job_id)
            self._change(c,job_id,state='QC',render_lease_until=None,retry_at=None,render_path=path,artifact_sha256=sha,captions=dumps(captions or [])); self._event(c,job_id,'render_finished',artifact_sha256=sha)
        return self.get_job(job_id)
    def run_qc(self,job_id):
        from .qc import inspect_media
        j=self.get_job(job_id)
        if j['state']!='QC': raise GateError('Job is not awaiting QC.')
        report=inspect_media(j['render_path'],j['captions'])
        with self._tx() as c:
            latest=self._job(c,job_id)
            if latest['artifact_sha256']!=j['artifact_sha256'] or latest['revision']!=j['revision']: raise ConflictError('Artifact changed during QC.')
            try: self._rights(c,job_id); rights=True
            except GateError: rights=False
            report['checks']['rights']=rights
            duplicate=c.execute("SELECT 1 FROM jobs WHERE id<>? AND artifact_sha256=? AND state IN ('SCHEDULED','PUBLISHED','ANALYZED')",(job_id,j['artifact_sha256'])).fetchone()
            report['checks']['originality']=not bool(duplicate)
            report['originality_scope']='Exact artifact duplicate check only; human editorial review is still required.'
            report['artifact_sha256']=file_hash(j['render_path'])
            report['passed']=report['artifact_sha256']==j['artifact_sha256'] and all(report['checks'].get(k) is True for k in QC_CHECKS)
            self._change(c,job_id,qc=dumps(report),release_sha256=None,release_approved_by=None)
            self._event(c,job_id,'qc_completed',passed=report['passed'])
        return report
    def approve_release(self,job_id,actor='human',artifact_sha256=None,revision=None):
        with self._tx() as c:
            j=self._job(c,job_id); self._approval(j); self._rights(c,job_id); self._artifact(j)
            if revision is not None and revision!=j['revision']: raise ConflictError('Final release decision is for a stale script revision.')
            if j['state']!='QC' or not json.loads(j['qc'] or '{}').get('passed'): raise GateError('Passing QC is required before final release review.')
            if not actor.strip() or artifact_sha256!=j['artifact_sha256']: raise ConflictError('Explicit human approval must identify the current artifact hash.')
            self._change(c,job_id,release_sha256=artifact_sha256,release_approved_by=actor); self._event(c,job_id,'release_approved',actor,artifact_sha256=artifact_sha256,revision=j['revision'],preview_id=j['active_preview_id'])
        return self.get_job(job_id)
    def schedule(self,job_id,when_iso,platforms=None):
        platforms=platforms or ['youtube','instagram','tiktok']; when=timestamp(when_iso)
        if not platforms or len(set(platforms))!=len(platforms) or not set(platforms)<=PLATFORMS: raise GateError('Unsupported or duplicate platforms.')
        with self._tx() as c:
            j=self._job(c,job_id); self._publish_gates(c,j)
            if j['state'] not in {'QC','SCHEDULED'}: raise GateError('Job cannot be scheduled in '+j['state'])
            day=self._day(c,when)
            already=c.execute('SELECT 1 FROM reservations WHERE job_id=? AND revision=? AND day=?',(job_id,j['revision'],day)).fetchone()
            if not already and c.execute('SELECT count(*) FROM reservations WHERE day=?',(day,)).fetchone()[0]>=self._setting(c,'daily_video_limit'): raise GateError('Daily unique-video publication limit reached.')
            existing=c.execute('SELECT * FROM deliveries WHERE job_id=?',(job_id,)).fetchall()
            if existing:
                if all(r['scheduled_at']==when and r['platform'] in platforms for r in existing) and len(existing)==len(platforms): return [dict(r) for r in existing]
                raise ConflictError('Already scheduled. Cancel before changing this schedule.')
            c.execute('INSERT OR IGNORE INTO reservations VALUES(?,?,?)',(job_id,j['revision'],day))
            for platform in platforms:
                try: c.execute('INSERT INTO deliveries(id,job_id,revision,platform,fingerprint,scheduled_at,day,status) VALUES(?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,job_id,j['revision'],platform,j['artifact_sha256'],when,day,'SCHEDULED'))
                except sqlite3.IntegrityError as e: raise ConflictError('This exact video already has a delivery for '+platform) from e
            self._change(c,job_id,state='SCHEDULED'); self._event(c,job_id,'scheduled',platforms=platforms,at=when)
        return self.get_job(job_id)['deliveries']
    def configure_publication(self,enabled,platform_accounts=None,actor='human'):
        with self._tx() as c:
            if not actor.strip(): raise GateError('Approval actor is required.')
            self._set(c,'publication_enabled',bool(enabled))
            if platform_accounts is not None:
                if not set(platform_accounts)<=PLATFORMS or any(not isinstance(v,str) or not v.strip() for v in platform_accounts.values()): raise GateError('Invalid platform account authorization.')
                self._set(c,'platform_accounts',platform_accounts)
            self._event(c,None,'publication_authorization',actor,enabled=bool(enabled),platforms=list(platform_accounts or {}))
    def publish_due(self,publishers,now=None,dry_run=True):
        now=self.clock() if now is None else timestamp(now); results=[]
        with self._connect() as c:
            ids=[r[0] for r in c.execute("SELECT id FROM deliveries WHERE dispatch_mode='api' AND status IN ('SCHEDULED','RETRYING') AND scheduled_at<=? AND (retry_at IS NULL OR retry_at<=?) ORDER BY scheduled_at",(now,now))]
        for delivery_id in ids:
            with self._tx() as c:
                row=c.execute('SELECT * FROM deliveries WHERE id=?',(delivery_id,)).fetchone()
                if row['dispatch_mode']!='api' or row['status'] not in {'SCHEDULED','RETRYING'} or row['scheduled_at']>now or (row['retry_at'] is not None and row['retry_at']>now): continue
                j=self._job(c,row['job_id'])
                try:
                    self._publish_gates(c,j)
                    if row['revision']!=j['revision']: raise GateError('Scheduled revision is stale.')
                    if not dry_run:
                        if not self._setting(c,'publication_enabled'): raise GateError('Live publication has not been authorized.')
                        if row['platform'] not in self._setting(c,'platform_accounts'): raise GateError('Platform account is not authorized.')
                        if row['platform'] not in publishers: raise GateError('No connected publisher for '+row['platform'])
                        expected_account=self._setting(c,'platform_accounts')[row['platform']]
                        try: adapter_account=getattr(publishers[row['platform']],'account_id',None)
                        except Exception: raise GateError('Publisher account identity could not be verified.') from None
                        if not isinstance(adapter_account,str) or adapter_account!=expected_account: raise GateError('Publisher account does not match the explicitly authorized platform account.')
                        actual_day=self._day(c,now)
                        already=c.execute('SELECT 1 FROM reservations WHERE job_id=? AND revision=? AND day=?',(j['id'],j['revision'],actual_day)).fetchone()
                        if not already:
                            if c.execute('SELECT count(*) FROM reservations WHERE day=?',(actual_day,)).fetchone()[0]>=self._setting(c,'daily_video_limit'): raise GateError('Actual delivery day has reached its unique-video limit.')
                            c.execute('INSERT INTO reservations VALUES(?,?,?)',(j['id'],j['revision'],actual_day))
                except GateError as e:
                    results.append({'delivery_id':delivery_id,'status':'BLOCKED','reason':str(e)}); continue
                if dry_run:
                    results.append({'delivery_id':delivery_id,'status':'DRY_RUN','platform':row['platform'],'would_publish':True,'no_external_request':True}); continue
                c.execute("UPDATE deliveries SET status='IN_FLIGHT',attempts=attempts+1,lease_until=?,account_id=? WHERE id=?",(now+300,expected_account,delivery_id))
                self._event(c,j['id'],'delivery_claimed',platform=row['platform'],delivery_id=delivery_id)
                job=self._decode(j); delivery=dict(row)
            try:
                result=publishers[delivery['platform']].publish(job,idempotency_key=delivery_id)
                queued=isinstance(result,dict) and result.get('status')=='SUBMITTED' and bool(result.get('external_id'))
                verified=isinstance(result,dict) and result.get('verified') is True and bool(result.get('external_id')) and bool(result.get('url'))
                if not queued and not verified:
                    raise AmbiguousPublishError('Provider response did not verify a durable receipt or published item.')
            except RetryablePublishError as e:
                with self._tx() as c:
                    attempts=c.execute('SELECT attempts FROM deliveries WHERE id=?',(delivery_id,)).fetchone()[0]
                    retry=attempts<5; state='RETRYING' if retry else 'FAILED'
                    c.execute('UPDATE deliveries SET status=?,retry_at=?,lease_until=NULL,error=? WHERE id=?',(state,now+min(3600,30*(2**(attempts-1))),str(e)[:400],delivery_id))
                    self._change(c,job['id'],state=state,error=str(e)[:400]); self._event(c,job['id'],'delivery_safe_failure',delivery_id=delivery_id,retry=retry)
                results.append({'delivery_id':delivery_id,'status':state}); continue
            except Exception as e:
                with self._tx() as c:
                    c.execute("UPDATE deliveries SET status='UNKNOWN',lease_until=NULL,error=? WHERE id=?",(type(e).__name__+': submission outcome uncertain',delivery_id))
                    self._change(c,job['id'],state='FAILED',error='Publication outcome uncertain. Reconcile before any retry.')
                    self._event(c,job['id'],'delivery_uncertain',delivery_id=delivery_id)
                results.append({'delivery_id':delivery_id,'status':'UNKNOWN','requires_reconciliation':True}); continue
            if queued and not verified:
                with self._tx() as c:
                    c.execute("UPDATE deliveries SET status='SUBMITTED',external_id=?,url=?,lease_until=NULL,error=NULL WHERE id=?",(str(result['external_id']),result.get('url'),delivery_id))
                    self._event(c,job['id'],'provider_receipt_recorded',delivery_id=delivery_id,external_id=str(result['external_id']))
                results.append({'delivery_id':delivery_id,'status':'SUBMITTED','external_id':result['external_id']}); continue
            with self._tx() as c:
                c.execute("UPDATE deliveries SET status='PUBLISHED',external_id=?,url=?,lease_until=NULL,error=NULL WHERE id=?",(str(result['external_id']),str(result['url']),delivery_id))
                remaining=c.execute("SELECT count(*) FROM deliveries WHERE job_id=? AND status<>'PUBLISHED'",(job['id'],)).fetchone()[0]
                self._change(c,job['id'],state='PUBLISHED' if remaining==0 else 'SCHEDULED',error=None)
                self._event(c,job['id'],'publication_verified',delivery_id=delivery_id,external_id=str(result['external_id']),url=str(result['url']))
            results.append({'delivery_id':delivery_id,'status':'PUBLISHED','url':result['url']})
        return results
    def reconcile_submissions(self,publishers):
        """Read-only provider polling. Never repeats the creation request."""
        with self._connect() as c:
            rows=[dict(r) for r in c.execute("SELECT * FROM deliveries WHERE dispatch_mode='api' AND status='SUBMITTED'")]
        results=[]
        for row in rows:
            adapter=publishers.get(row['platform'])
            if adapter is None or not hasattr(adapter,'verify'):
                results.append({'delivery_id':row['id'],'status':'SUBMITTED','reason':'Verification adapter unavailable'}); continue
            try: account_id=getattr(adapter,'account_id',None)
            except Exception: account_id=None
            if not row['account_id'] or account_id!=row['account_id']:
                results.append({'delivery_id':row['id'],'status':'SUBMITTED','reason':'Verification account does not match the original submission; no provider request made'}); continue
            try: result=adapter.verify(row['external_id'])
            except Exception:
                results.append({'delivery_id':row['id'],'status':'SUBMITTED','reason':'Verification unavailable; no resubmission'}); continue
            if result.get('verified') is True and result.get('external_id')==row['external_id'] and result.get('url'):
                with self._tx() as c:
                    c.execute("UPDATE deliveries SET status='PUBLISHED',url=? WHERE id=? AND status='SUBMITTED'",(result['url'],row['id']))
                    remaining=c.execute("SELECT count(*) FROM deliveries WHERE job_id=? AND status<>'PUBLISHED'",(row['job_id'],)).fetchone()[0]
                    self._change(c,row['job_id'],state='PUBLISHED' if remaining==0 else 'SCHEDULED')
                    self._event(c,row['job_id'],'publication_verified',delivery_id=row['id'],external_id=row['external_id'],url=result['url'])
                results.append({'delivery_id':row['id'],'status':'PUBLISHED','url':result['url']})
            elif result.get('status')=='FAILED':
                with self._tx() as c:
                    c.execute("UPDATE deliveries SET status='UNKNOWN',error='Provider reported failure; inspect remote record before retry' WHERE id=?",(row['id'],))
                    self._change(c,row['job_id'],state='FAILED',error='Provider submission failed; manual review required.')
                    self._event(c,row['job_id'],'provider_submission_failed',delivery_id=row['id'])
                results.append({'delivery_id':row['id'],'status':'UNKNOWN'})
            else: results.append({'delivery_id':row['id'],'status':'SUBMITTED'})
        return results
    def recover_expired_leases(self,now=None):
        now=self.clock() if now is None else timestamp(now)
        with self._tx() as c:
            rows=c.execute("SELECT * FROM deliveries WHERE status='IN_FLIGHT' AND lease_until<?",(now,)).fetchall()
            for row in rows:
                c.execute("UPDATE deliveries SET status='UNKNOWN',lease_until=NULL,error='Worker lease expired; reconcile external outcome' WHERE id=?",(row['id'],))
                self._change(c,row['job_id'],state='FAILED',error='Worker stopped during publication. Reconcile external outcome.')
                self._event(c,row['job_id'],'expired_delivery_lease',delivery_id=row['id'])
            renders=c.execute("SELECT id FROM jobs WHERE state='RENDERING' AND render_lease_until<?",(now,)).fetchall()
            for row in renders:
                self._change(c,row['id'],state='RETRYING',render_lease_until=None,retry_at=now+60,error='Render lease expired; retry after backoff.')
                self._event(c,row['id'],'expired_render_lease')
            return len(rows)+len(renders)
    def reconcile_delivery(self,delivery_id,*,published,verified_evidence,external_id=None,url=None,actor='human'):
        if not actor.strip() or not verified_evidence.strip(): raise GateError('Explicit operator evidence is required.')
        if published and (not external_id or not url): raise GateError('A verified external ID and URL are required.')
        with self._tx() as c:
            row=c.execute('SELECT * FROM deliveries WHERE id=?',(delivery_id,)).fetchone()
            if not row or row['status']!='UNKNOWN': raise GateError('Only uncertain deliveries can be reconciled.')
            if row['dispatch_mode']=='manual': raise GateError('Use record_manual_delivery for manual evidence; manual deliveries never become retryable.')
            state='PUBLISHED' if published else 'RETRYING'
            c.execute('UPDATE deliveries SET status=?,external_id=?,url=?,retry_at=?,error=NULL WHERE id=?',(state,external_id,url,self.clock() if not published else None,delivery_id))
            remaining=c.execute("SELECT count(*) FROM deliveries WHERE job_id=? AND status<>'PUBLISHED'",(row['job_id'],)).fetchone()[0]
            self._change(c,row['job_id'],state='PUBLISHED' if remaining==0 else 'SCHEDULED')
            self._event(c,row['job_id'],'delivery_reconciled',actor,delivery_id=delivery_id,published=published,evidence=verified_evidence)
    def cancel(self,job_id,actor='human'):
        with self._tx() as c:
            j=self._job(c,job_id); self._mutable(c,j,allow_rendering=True); self._change(c,job_id,state='CANCELLED',render_lease_until=None,render_token=None); self._event(c,job_id,'cancelled',actor)
        return self.get_job(job_id)
    def kill_switch(self,enabled=True,actor='human'):
        with self._tx() as c: self._set(c,'kill_switch',bool(enabled)); self._event(c,None,'kill_switch',actor,enabled=bool(enabled))
    def approve_budget(self,amount,actor='human'):
        if not isinstance(amount,(int,float)) or not math.isfinite(amount) or not 0<=amount<=150: raise GateError('Approved monthly budget must be between $0 and $150.')
        with self._tx() as c: self._set(c,'approved_budget',float(amount)); self._event(c,None,'budget_authorized',actor,monthly_usd=amount)
    def reserve_cost(self,provider,estimated_usd):
        if not isinstance(estimated_usd,(int,float)) or not math.isfinite(estimated_usd) or estimated_usd<0: raise GateError('Invalid cost estimate.')
        cost_id=uuid.uuid4().hex
        with self._tx() as c:
            self._active(c); month=self._month(c)
            used=c.execute("SELECT coalesce(sum(CASE WHEN status='RESERVED' THEN reserved WHEN status='SETTLED' THEN actual ELSE 0 END),0) FROM costs WHERE month=?",(month,)).fetchone()[0]
            if used+estimated_usd>min(self._setting(c,'approved_budget'),self._setting(c,'monthly_ceiling'))+1e-9: raise GateError('Cost exceeds authorized monthly budget.')
            c.execute('INSERT INTO costs VALUES(?,?,?,?,?,?,?)',(cost_id,provider,float(estimated_usd),None,'RESERVED',month,self.clock())); self._event(c,None,'cost_reserved',provider=provider,reservation=cost_id,usd=estimated_usd)
        return cost_id
    def settle_cost(self,reservation_id,actual_usd):
        if not isinstance(actual_usd,(int,float)) or not math.isfinite(actual_usd) or actual_usd<0: raise GateError('Invalid actual cost.')
        with self._tx() as c:
            row=c.execute('SELECT * FROM costs WHERE id=?',(reservation_id,)).fetchone()
            if not row or row['status']!='RESERVED': raise ConflictError('Cost reservation is not open.')
            c.execute("UPDATE costs SET actual=?,status='SETTLED' WHERE id=?",(float(actual_usd),reservation_id))
            if actual_usd>row['reserved']:
                self._set(c,'kill_switch',True); self._event(c,None,'cost_overrun',reservation=reservation_id,actual_usd=actual_usd,reserved_usd=row['reserved'])
            self._event(c,None,'cost_settled',reservation=reservation_id,actual_usd=actual_usd)
    def release_cost(self,reservation_id):
        with self._tx() as c:
            if c.execute("UPDATE costs SET status='RELEASED' WHERE id=? AND status='RESERVED'",(reservation_id,)).rowcount!=1: raise ConflictError('Cost reservation is not open.')
    def record_metrics(self,job_id,platform,values,source,observed_at=None):
        allowed={'views','watch_time_seconds','average_view_duration_seconds','retention_rate','completion_rate','shares','saves','comments','followers_gained','follower_conversion_rate','likes'}
        if not source.startswith('https://') or not values or not set(values)<=allowed: raise GateError('Metrics require a provider evidence URL and known fields.')
        for k,v in values.items():
            if v is None: continue
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or (k.endswith('_rate') and v>1): raise GateError('Invalid metric '+k)
        with self._tx() as c:
            row=c.execute("SELECT * FROM deliveries WHERE job_id=? AND platform=? AND status='PUBLISHED'",(job_id,platform)).fetchone()
            if not row: raise GateError('Metrics require a verified published delivery.')
            c.execute('INSERT INTO metrics VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,job_id,platform,row['external_id'],self.clock() if observed_at is None else timestamp(observed_at),source,dumps(values)))
            j=self._job(c,job_id)
            if j['state'] in {'PUBLISHED','ANALYZED'}: self._change(c,job_id,state='ANALYZED')
            self._event(c,job_id,'metrics_recorded',platform=platform,source=source)
    def metrics_report(self):
        with self._connect() as c:
            rows=[]
            for row in c.execute('SELECT * FROM metrics ORDER BY observed_at DESC'):
                d=dict(row); d['values']=json.loads(d.pop('values_json')); rows.append(d)
            return rows
    def audit_log(self,limit=30):
        with self._connect() as c:
            rows=[]
            for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(min(max(int(limit),1),1000),)):
                d=dict(r); d['payload']=json.loads(d['payload']); rows.append(d)
            return rows
    def status(self):
        with self._connect() as c:
            settings={r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
            month=self._month(c)
            spent=c.execute("SELECT coalesce(sum(actual),0) FROM costs WHERE status='SETTLED' AND month=?",(month,)).fetchone()[0]
            reserved=c.execute("SELECT coalesce(sum(reserved),0) FROM costs WHERE status='RESERVED' AND month=?",(month,)).fetchone()[0]
            return {**settings,'costs':{'month':month,'approved_usd':settings['approved_budget'],'spent_usd':spent,'reserved_usd':reserved},'counts':dict(c.execute('SELECT state,count(*) FROM jobs GROUP BY state').fetchall()),'uncertain_deliveries':c.execute("SELECT count(*) FROM deliveries WHERE status='UNKNOWN'").fetchone()[0]}
