import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from integrations.http import IntegrationBlocked
from integrations.supabase_storage import SupabaseStorage,local_plan,DEFAULT_PROJECT,DEFAULT_BUCKET

class FakeBucket:
    def __init__(self):self.content=b'';self.uploads=[];self.signs=0;self.bad=False;self.fail=False
    def upload(self,*,path,file,file_options):
        self.uploads.append((path,file_options));self.content=file.read()
        if self.fail:raise TimeoutError('secret-key-in-provider-error')
    def download(self,key):return b'wrong bytes' if self.bad else self.content
    def create_signed_url(self,key,expires):
        self.signs+=1;return {'signedURL':DEFAULT_PROJECT+'/storage/v1/object/sign/'+DEFAULT_BUCKET+'/'+key+'?token=secret-bearer'}
class FakeClient:
    def __init__(self):self.storage=self;self.bucket=FakeBucket();self.public=False
    def get_bucket(self,bucket):return {'id':bucket,'public':self.public}
    def from_(self,bucket):return self.bucket

class SupabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'video.mp4';self.path.write_bytes(b'fixture video')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest();self.client=FakeClient();self.adapter=SupabaseStorage(self.client)
        self.env=patch.dict(os.environ,{'ALLOW_EXTERNAL_REQUESTS':'true','ALLOW_STORAGE_UPLOADS':'true'});self.env.start();self.addCleanup(self.env.stop)
    def test_offline_plan_never_connects_or_shares(self):
        plan=local_plan(self.path,self.sha);self.assertEqual(plan['external_requests'],0);self.assertFalse(plan['storage_verified']);self.assertNotIn('url',plan)
    def test_upload_requires_separate_switch(self):
        with patch.dict(os.environ,{'ALLOW_STORAGE_UPLOADS':'false'}),self.assertRaises(IntegrationBlocked):self.adapter.upload_verified(self.path,self.sha)
        self.assertEqual(self.client.bucket.uploads,[])
    def test_public_bucket_blocked(self):
        self.client.public=True
        with self.assertRaises(IntegrationBlocked):self.adapter.upload_verified(self.path,self.sha)
        self.assertEqual(self.client.bucket.uploads,[])
    def test_full_download_hash_verified_no_public_url(self):
        result=self.adapter.upload_verified(self.path,self.sha)
        self.assertTrue(result['storage_verified']);self.assertFalse(result['distribution_authorized']);self.assertNotIn('url',result)
        self.assertEqual(self.client.bucket.uploads[0][1]['upsert'],'false');self.assertEqual(self.client.bucket.signs,0)
    def test_remote_bytes_mismatch_blocks_verification(self):
        self.client.bucket.bad=True
        with self.assertRaisesRegex(IntegrationBlocked,'differs'):self.adapter.upload_verified(self.path,self.sha)
    def test_uncertain_upload_redacts_error_and_never_retries(self):
        self.client.bucket.fail=True
        with self.assertRaises(IntegrationBlocked) as err:self.adapter.upload_verified(self.path,self.sha)
        self.assertNotIn('secret',str(err.exception));self.assertEqual(len(self.client.bucket.uploads),1)
        receipt=self.adapter.verify_existing(local_plan(self.path,self.sha));self.assertTrue(receipt['storage_verified']);self.assertEqual(len(self.client.bucket.uploads),1)
    def test_signed_link_requires_separate_sharing_authorization(self):
        receipt=self.adapter.upload_verified(self.path,self.sha)
        with self.assertRaises(IntegrationBlocked):self.adapter.signed_read_url(receipt)
        self.assertEqual(self.client.bucket.signs,0)
        signed=self.adapter.signed_read_url(receipt,sharing_authorized=True);self.assertIn('token=',signed['url']);self.assertFalse(signed['distribution_authorized'])
    def test_project_host_and_file_hash_are_pinned(self):
        for url in ('https://evil.test','http://'+DEFAULT_PROJECT[8:],'https://user:secret@'+DEFAULT_PROJECT[8:]):
            with self.assertRaises(ValueError):SupabaseStorage(self.client,url)
        with self.assertRaises(ValueError):self.adapter.upload_verified(self.path,'0'*64)
        self.assertEqual(self.client.bucket.uploads,[])

if __name__=='__main__':unittest.main()
