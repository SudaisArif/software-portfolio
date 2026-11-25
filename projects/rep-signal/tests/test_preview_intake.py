import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from media_engine import Engine,GateError,ConflictError
from media_engine.engine import file_hash
from preview_intake import import_review_artifact


def measured_fixture():return {'checks':dict.fromkeys(('video','audio','duration','resolution','captions'),True),'measurements':{'duration_seconds':21}}

class PreviewIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.engine=Engine(self.root/'data/test.db');self.video=self.root/'film.mp4';self.video.write_bytes(b'isolated mock rendered video')
        self.manifest=self.root/'film.json';self.source=self.root/'source.bin';self.source.write_bytes(b'original fixture source')
        self.raw={'title':'An unapproved review video','script':'A thoughtful training decision.','sources':[{'url':'https://example.test/research'}],
                  'captions':[{'start':0,'end':21,'text':'A thoughtful training decision.'}],'audio_mode':'narrated','sha256':file_hash(self.video),
                  'human_approved':True,'publishable':True,
                  'assets':[{'kind':kind,'local_path':str(self.source),'sha256':file_hash(self.source),'rights_status':'original','license_url':'','provenance':'Isolated test fixture.'} for kind in ('visuals','narration','sound_design','font')]}
        self.probe=patch('media_engine.qc.inspect_media',side_effect=lambda *a,**k:measured_fixture());self.probe.start();self.addCleanup(self.probe.stop)
    def intake(self,**kwargs):
        self.manifest.write_text(json.dumps(self.raw))
        return import_review_artifact(self.engine,self.video,self.manifest,repository_root=self.root,**kwargs)
    def approve_fixture_script(self,result):
        job=result['job'];return self.engine.review_script(job['id'],'approve',revision=job['revision'],actor='isolated-test-human')
    def stage(self,result):return self.engine.stage_preview(result['preview']['id'],revision=result['job']['revision'],artifact_sha256=result['preview']['artifact_sha256'])
    def test_import_creates_review_binding_without_approval(self):
        r=self.intake();j=r['job'];p=r['preview']
        self.assertEqual(j['state'],'HUMAN_REVIEW');self.assertIsNone(j['approved_revision']);self.assertIsNone(j['release_sha256'])
        self.assertFalse(r['approval_created']);self.assertFalse(p['human_approved']);self.assertFalse(self.engine.status()['publication_enabled'])
        self.assertTrue(r['qc']['technical_passed']);self.assertEqual(p['revision'],j['revision']);self.assertEqual(file_hash(p['path']),p['artifact_sha256'])
        self.assertNotEqual(p['path'],str(self.video));self.assertEqual(Path(p['path']).stat().st_mode&0o777,0o600)
        with self.assertRaises(GateError):self.stage(r)
        self.assertEqual(self.engine.status()['costs']['spent_usd'],0)
    def test_reimport_is_idempotent(self):
        a=self.intake();b=self.intake();self.assertEqual(a['preview']['id'],b['preview']['id']);self.assertEqual(len(self.engine.list_jobs()),1)
    def test_final_release_is_separate_and_does_not_enable_publication(self):
        r=self.intake();self.approve_fixture_script(r);s=self.stage(r)
        self.assertEqual(s['job']['state'],'QC');self.assertTrue(s['qc']['passed']);self.assertIsNone(s['job']['release_sha256'])
        with self.assertRaises(ConflictError):self.engine.approve_release(s['job']['id'],artifact_sha256='wrong')
        self.engine.approve_release(s['job']['id'],artifact_sha256=r['preview']['artifact_sha256'],actor='isolated-test-human')
        self.assertFalse(self.engine.status()['publication_enabled'])
    def test_rights_unclear_preview_plays_but_cannot_release(self):
        self.raw['assets'][0]['rights_status']='preview_only';r=self.intake()
        self.assertTrue(r['qc']['technical_passed']);self.assertFalse(r['qc']['checks']['rights']);self.approve_fixture_script(r);s=self.stage(r)
        self.assertFalse(s['qc']['passed'])
        with self.assertRaises(GateError):self.engine.approve_release(r['job']['id'],artifact_sha256=r['preview']['artifact_sha256'])
    def test_visual_essay_never_fabricates_narration_asset(self):
        self.raw['audio_mode']='visual_essay';self.raw['assets']=[a for a in self.raw['assets'] if a['kind']!='narration']
        r=self.intake();self.approve_fixture_script(r);self.assertTrue(self.stage(r)['qc']['passed'])
        self.assertNotIn('narration',{a['kind'] for a in self.engine.list_assets(r['job']['id'])})
    def test_source_audio_can_have_no_separate_sound_design(self):
        self.raw['audio_mode']='source_audio';self.raw['assets']=[a for a in self.raw['assets'] if a['kind']!='sound_design']
        r=self.intake();self.approve_fixture_script(r);self.assertTrue(self.stage(r)['qc']['passed'])
    def test_wrong_video_hash_rejected_without_job(self):
        self.raw['sha256']='0'*64
        with self.assertRaises(GateError):self.intake()
        self.assertEqual(self.engine.list_jobs(),[])
    def test_caption_script_mismatch_never_attaches(self):
        self.raw['captions'][0]['text']='This is another script.'
        with self.assertRaises(GateError):self.intake()
        self.assertEqual(self.engine.list_jobs(),[])
    def test_existing_job_requires_exact_revision_script_and_sources(self):
        r=self.intake()
        with self.assertRaises(GateError):self.intake(job_id=r['job']['id'])
        self.raw['script']='Other script';self.raw['captions'][0]['text']='Other script'
        with self.assertRaises(GateError):self.intake(job_id=r['job']['id'],expected_revision=1)
    def test_stale_preview_cannot_stage_after_script_change(self):
        r=self.intake();self.engine.set_script(r['job']['id'],'Changed script',expected_revision=1)
        self.engine.review_script(r['job']['id'],'approve',revision=2,actor='isolated-test-human')
        with self.assertRaises(ConflictError):self.engine.stage_preview(r['preview']['id'],revision=2,artifact_sha256=r['preview']['artifact_sha256'])
        self.assertIsNone(self.engine.get_job(r['job']['id'])['release_sha256'])
    def test_snapshot_preserves_video_but_changed_inputs_block_staging(self):
        r=self.intake();self.video.write_bytes(b'overwritten outer preview');self.approve_fixture_script(r)
        self.assertEqual(file_hash(r['preview']['path']),r['preview']['artifact_sha256'])
        self.source.write_bytes(b'changed provenance asset')
        with self.assertRaises(GateError):self.stage(r)
    def test_tampered_snapshot_manifest_blocks_staging(self):
        r=self.intake();self.approve_fixture_script(r);Path(r['preview']['manifest_path']).write_text('{}')
        with self.assertRaises(GateError):self.stage(r)
    def test_technical_failure_never_stages(self):
        self.probe.stop()
        with patch('media_engine.qc.inspect_media',return_value={'checks':{'video':False}}):r=self.intake()
        self.approve_fixture_script(r)
        with self.assertRaises(GateError):self.stage(r)
    def test_kill_switch_blocks_intake_before_snapshot(self):
        self.engine.kill_switch(True)
        with self.assertRaises(GateError):self.intake()
        self.assertFalse((self.root/'data/review-artifacts').exists())
    def test_intake_does_not_overwrite_owner_decision(self):
        r=self.intake();self.approve_fixture_script(r);again=self.intake()
        self.assertEqual(again['job']['state'],'APPROVED');self.assertEqual(again['job']['script_approved_by'],'isolated-test-human')
    def test_extra_unknown_asset_blocks_release(self):
        extra=copy.deepcopy(self.raw['assets'][0]);extra.update(kind='music',rights_status='unknown');self.raw['assets'].append(extra)
        r=self.intake();self.assertFalse(r['qc']['checks']['rights'])

if __name__=='__main__':unittest.main()
