"""Private Supabase review backups through the official Python client.

Contract checked 2026-11-17 against official Supabase docs:
https://supabase.com/docs/reference/python/storage-from-upload
https://supabase.com/docs/reference/python/storage-from-download
https://supabase.com/docs/reference/python/storage-getbucket
https://supabase.com/docs/reference/python/storage-from-createsignedurl

No bucket creation, public ACL, upsert, deletion, billing changes or publication.
Full authenticated download SHA-256 verifies bytes, not merely object metadata.
No live connection is attempted during import or local planning.
"""
import hashlib
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from .http import IntegrationBlocked, credential

MAX_BYTES=50_000_000
DEFAULT_PROJECT='https://juaytlaetgylkwcyqjrk.supabase.co'
DEFAULT_BUCKET='rep-signal-media'


def _project(value):
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or not re.fullmatch(r'[a-z0-9]{20}\.supabase\.co',p.hostname) or p.username or p.password or p.port or p.path not in ('','/') or p.query or p.fragment:
        raise ValueError('Use the exact HTTPS Supabase project URL without credentials or paths')
    return 'https://'+p.hostname


def _field(value,name):
    return value.get(name) if isinstance(value,dict) else getattr(value,name,None)


def local_plan(path,expected_sha256,bucket=DEFAULT_BUCKET,project_url=DEFAULT_PROJECT):
    path=Path(path)
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,62}',bucket):raise ValueError('Invalid private bucket name')
    if not path.is_file() or path.suffix.lower()!='.mp4' or not 0<path.stat().st_size<=MAX_BYTES:raise ValueError('Private review backups require MP4 files under 50 MB')
    with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=expected_sha256:raise ValueError('Review artifact changed; upload blocked')
    return {'provider':'supabase','project_url':_project(project_url),'bucket':bucket,'key':f'reviews/{actual}.mp4','sha256':actual,'size':path.stat().st_size,
            'purpose':'private_review_backup','public':False,'upsert':False,'storage_verified':False,'distribution_authorized':False,'external_requests':0}


class SupabaseStorage:
    def __init__(self,client=None,project_url=None):
        self.client=client; self.project_url=_project(project_url or os.getenv('SUPABASE_URL') or DEFAULT_PROJECT)
    def _client(self):
        if os.getenv('ALLOW_EXTERNAL_REQUESTS')!='true':raise IntegrationBlocked('External requests are disabled; Supabase connection authorization is required')
        if self.client is not None:return self.client
        key=credential('SUPABASE_STORAGE_KEY')
        try:from supabase import create_client
        except ImportError:raise IntegrationBlocked('Install requirements-supabase.txt before connecting Supabase storage') from None
        # A least-privilege authenticated Storage credential/RLS policy is preferred.
        # Never obtain or widen permissions automatically.
        try:self.client=create_client(self.project_url,key)
        except Exception:raise IntegrationBlocked("Supabase client could not be initialized; no credential values were exposed") from None
        return self.client
    def _private_bucket(self,client,bucket):
        try:detail=client.storage.get_bucket(bucket)
        except Exception:raise IntegrationBlocked('Private bucket could not be verified; no upload was attempted') from None
        if _field(detail,'public') is not False or _field(detail,'id')!=bucket:raise IntegrationBlocked('Storage bucket must exist and be explicitly private')
        return client.storage.from_(bucket)
    def upload_verified(self,path,expected_sha256,bucket=DEFAULT_BUCKET):
        plan=local_plan(path,expected_sha256,bucket,self.project_url)
        if os.getenv('ALLOW_STORAGE_UPLOADS')!='true':raise IntegrationBlocked('Private storage uploads are disabled pending explicit owner authorization')
        client=self._client(); storage=self._private_bucket(client,bucket)
        try:
            with Path(path).open('rb') as file:
                storage.upload(path=plan['key'],file=file,file_options={'content-type':'video/mp4','cache-control':'3600','upsert':'false'})
        except Exception:raise IntegrationBlocked('Upload outcome is unverified; inspect the immutable object key before retrying. No overwrite or automatic retry occurred.') from None
        receipt=self.verify_existing(plan)
        receipt['upload_attempted']=True
        return receipt
    def verify_existing(self,record):
        # This is the safe recovery path following an interrupted upload; it only reads.
        if record.get('project_url')!=self.project_url or not re.fullmatch(r'reviews/[0-9a-f]{64}\.mp4',record.get('key','')) or record.get('key')!=f"reviews/{record.get('sha256')}.mp4":raise ValueError('Invalid content-addressed Supabase receipt')
        if isinstance(record.get('size'),bool) or not isinstance(record.get('size'),int) or not 0<record['size']<=MAX_BYTES:raise ValueError('Invalid receipt size')
        client=self._client(); storage=self._private_bucket(client,record['bucket'])
        try:content=storage.download(record['key'])
        except Exception:raise IntegrationBlocked('Authenticated object download failed; backup remains unverified') from None
        if not isinstance(content,bytes) or len(content)!=record['size'] or hashlib.sha256(content).hexdigest()!=record['sha256']:raise IntegrationBlocked('Downloaded object differs from the local artifact; backup verification failed')
        return {**record,'storage_verified':True,'verification':'full_authenticated_download_sha256','verified_at':time.time(),'public':False,'distribution_authorized':False,'external_requests':'read_only_verification'}
    def signed_read_url(self,record,expires_seconds=3600,*,sharing_authorized=False):
        if sharing_authorized is not True:raise IntegrationBlocked('Creating a bearer download URL requires explicit sharing authorization')
        if isinstance(expires_seconds,bool) or not isinstance(expires_seconds,int) or not 60<=expires_seconds<=86400:raise ValueError('Signed read URL lifetime must be 1 minute–24 hours')
        verified=self.verify_existing(record); client=self._client(); storage=self._private_bucket(client,record['bucket'])
        try:result=storage.create_signed_url(record['key'],expires_seconds)
        except Exception:raise IntegrationBlocked('Could not create a private read URL') from None
        url=_field(result,'signedURL') or _field(result,'signedUrl')
        if not isinstance(url,str):raise IntegrationBlocked('Storage returned no signed read URL')
        p=urlsplit(url)
        if p.scheme!='https' or p.netloc!=urlsplit(self.project_url).netloc or not p.path.startswith('/storage/v1/object/sign/'+record['bucket']+'/') or p.username or p.password or not p.query:raise IntegrationBlocked('Storage returned an unexpected signed URL')
        # This value is a bearer secret: caller must write a private receipt and never print it.
        return {**verified,'url':url,'expires_at':time.time()+expires_seconds,'expires_in':expires_seconds,'sharing_authorized':True,'distribution_authorized':False}
