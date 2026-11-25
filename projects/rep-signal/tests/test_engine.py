import concurrent.futures
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from media_engine import Engine, GateError, ConflictError, RetryablePublishError, AmbiguousPublishError
from media_engine.qc import inspect_media

class FakePublisher:
    def __init__(self,account_id='fixture-channel'): self.calls=[]; self.account_id=account_id
    def publish(self,job,idempotency_key):
        self.calls.append(idempotency_key)
        return {'verified':True,'external_id':'fake-'+idempotency_key,'url':'https://example.test/'+idempotency_key}

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name); self.now=1805126400.0
        self.e=Engine(self.path/'db.sqlite',clock=lambda:self.now)
        self.asset=self.path/'original.txt'; self.asset.write_text('Original test asset')
    def review_job(self,title='Test'):
        j=self.e.create_job(title)
        self.e.set_research(j['id'],[{'url':'https://example.test/research','title':'Fixture only'}],'Fixture evidence')
        return self.e.set_script(j['id'],'A specific next action beats a vague promise.')
    def add_original_assets(self,job_id):
        for kind in ('visuals','narration','sound_design','font'):
            self.e.add_asset(job_id,kind,self.asset,'original',provenance='Created by test fixture')
    def ready(self,title='Test',filename=None):
        j=self.review_job(title)
        self.e.review_script(j['id'],'approve',revision=j['revision'],actor='test-human')
        self.add_original_assets(j['id'])
        j=self.e.start_render(j['id'])
        media=self.path/(filename or j['id']+'.mp4'); media.write_bytes((filename or j['id']).encode())
        j=self.e.finish_render(j['id'],media,[{'start':0,'end':20,'text':'Fixture'}],revision=j['revision'],render_token=j['render_token'])
        with patch('media_engine.qc.inspect_media',return_value={'checks':dict.fromkeys(['video','audio','duration','resolution','captions'],True)}): self.e.run_qc(j['id'])
        return self.e.approve_release(j['id'],actor='test-human',artifact_sha256=j['artifact_sha256'])
    def schedule(self,j,platforms=None,offset=0):
        return self.e.schedule(j['id'],self.now+offset,platforms=platforms or ['youtube'])
    def live(self): self.e.configure_publication(True,{'youtube':'fixture-channel','instagram':'fixture-ig','tiktok':'fixture-tt'},actor='test-human')
    def test_default_no_spend_no_publish(self):
        status=self.e.status(); self.assertFalse(status['publication_enabled']); self.assertEqual(status['costs']['approved_usd'],0)
        with self.assertRaises(GateError): self.e.reserve_cost('provider',0.01)
    def test_cannot_bypass_script_review(self):
        j=self.review_job()
        with self.assertRaises(GateError): self.e.start_render(j['id'])
        with self.assertRaises(ConflictError): self.e.review_script(j['id'],'approve')
        with self.assertRaises(ConflictError): self.e.review_script(j['id'],'approve',revision=0)
    def test_revision_invalidates_every_approval(self):
        j=self.ready(); j=self.e.set_script(j['id'],'A revised script')
        self.assertEqual(j['state'],'HUMAN_REVIEW'); self.assertIsNone(j['approved_revision']); self.assertIsNone(j['release_sha256']); self.assertIsNone(j['qc'])
        with self.assertRaises(GateError): self.schedule(j)
    def test_preview_rights_cannot_enter_production(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1)
        self.e.add_asset(j['id'],'voice',self.asset,'preview_only',provenance='System voice preview')
        with self.assertRaises(GateError): self.e.start_render(j['id'])
    def test_missing_license_evidence_is_blocked(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1)
        self.e.add_asset(j['id'],'music',self.asset,'licensed',provenance='Claimed music')
        with self.assertRaises(GateError): self.e.start_render(j['id'])
    def test_tampered_source_or_video_blocks_publish(self):
        j=self.ready(); self.schedule(j); self.live()
        self.asset.write_text('Changed asset')
        p=FakePublisher(); result=self.e.publish_due({'youtube':p},dry_run=False)
        self.assertEqual(result[0]['status'],'BLOCKED'); self.assertFalse(p.calls)
    def test_final_artifact_hash_must_be_explicit(self):
        j=self.ready()
        with self.assertRaises(ConflictError): self.e.approve_release(j['id'],artifact_sha256='stale')
        Path(j['render_path']).write_bytes(b'tampered')
        with self.assertRaises(GateError): self.schedule(j)
    def test_dry_run_no_side_effects(self):
        j=self.ready(); self.schedule(j); p=FakePublisher()
        result=self.e.publish_due({'youtube':p})
        self.assertEqual(result[0]['status'],'DRY_RUN'); self.assertFalse(p.calls)
        self.assertEqual(self.e.get_job(j['id'])['state'],'SCHEDULED')
    def test_live_requires_separate_platform_authorization(self):
        j=self.ready(); self.schedule(j); p=FakePublisher()
        result=self.e.publish_due({'youtube':p},dry_run=False)
        self.assertEqual(result[0]['status'],'BLOCKED'); self.assertFalse(p.calls)
        self.e.configure_publication(True,{})
        self.assertEqual(self.e.publish_due({'youtube':p},dry_run=False)[0]['status'],'BLOCKED')
    def test_publisher_account_must_match_authorized_identity(self):
        j=self.ready(); self.schedule(j); self.live()
        wrong=FakePublisher('different-channel')
        result=self.e.publish_due({'youtube':wrong},dry_run=False)
        self.assertEqual(result[0]['status'],'BLOCKED'); self.assertFalse(wrong.calls)
        self.assertEqual(self.e.get_job(j['id'])['deliveries'][0]['attempts'],0)
        del wrong.account_id
        result=self.e.publish_due({'youtube':wrong},dry_run=False)
        self.assertEqual(result[0]['status'],'BLOCKED'); self.assertFalse(wrong.calls)
    def test_publish_verified_and_duplicate_retry_is_noop(self):
        j=self.ready(); self.schedule(j); self.live(); p=FakePublisher()
        self.assertEqual(self.e.publish_due({'youtube':p},dry_run=False)[0]['status'],'PUBLISHED')
        self.assertEqual(self.e.publish_due({'youtube':p},dry_run=False),[]); self.assertEqual(len(p.calls),1)
        with self.assertRaises(GateError): self.e.set_script(j['id'],'Change published item')
    def test_same_video_all_platforms_counts_once(self):
        j=self.ready(); self.schedule(j,['youtube','instagram','tiktok']); self.live(); p=FakePublisher()
        r=self.e.publish_due({'youtube':p,'instagram':FakePublisher('fixture-ig'),'tiktok':FakePublisher('fixture-tt')},dry_run=False)
        self.assertEqual(len(r),3); self.assertTrue(all(x['status']=='PUBLISHED' for x in r))
        other=self.ready('Second')
        with self.assertRaises(GateError): self.schedule(other)
    def test_overdue_delivery_cannot_bypass_actual_day_limit(self):
        a=self.ready('Yesterday'); self.schedule(a,offset=-86400)
        b=self.ready('Today'); self.schedule(b); self.live(); p=FakePublisher()
        r=self.e.publish_due({'youtube':p},dry_run=False)
        self.assertEqual([x['status'] for x in r],['BLOCKED','PUBLISHED']); self.assertEqual(len(p.calls),1)
    def test_concurrent_workers_claim_once(self):
        j=self.ready(); self.schedule(j); self.live(); p=FakePublisher()
        barrier=threading.Barrier(2)
        def run():
            e=Engine(self.path/'db.sqlite',clock=lambda:self.now); barrier.wait(); return e.publish_due({'youtube':p},dry_run=False)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(len(p.calls),1)
    def test_ambiguous_submission_never_auto_retries(self):
        j=self.ready(); self.schedule(j); self.live()
        class Unknown:
            account_id='fixture-channel'
            def publish(self,*a,**k): raise TimeoutError('potential accepted request')
        r=self.e.publish_due({'youtube':Unknown()},dry_run=False)
        self.assertEqual(r[0]['status'],'UNKNOWN'); self.now+=99999
        self.assertEqual(self.e.publish_due({'youtube':FakePublisher()},dry_run=False),[])
        with self.assertRaises(GateError): self.e.start_render(j['id'])
        with self.assertRaises(GateError): self.e.cancel(j['id'])
    def test_explicit_safe_failure_retries_after_backoff(self):
        j=self.ready(); self.schedule(j); self.live()
        class SafeFailure:
            account_id='fixture-channel'
            def publish(self,*a,**k): raise RetryablePublishError('Rejected before submission')
        self.assertEqual(self.e.publish_due({'youtube':SafeFailure()},dry_run=False)[0]['status'],'RETRYING')
        self.assertEqual(self.e.publish_due({'youtube':FakePublisher()},dry_run=False),[])
        self.now+=31
        self.assertEqual(self.e.publish_due({'youtube':FakePublisher()},dry_run=False)[0]['status'],'PUBLISHED')
    def test_provider_receipt_waits_for_verified_publication(self):
        j=self.ready(); self.schedule(j); self.live()
        class Queued:
            account_id='fixture-channel'
            calls=0; is_ready=False
            def publish(self,*a,**k): self.calls+=1; return {'status':'SUBMITTED','external_id':'queue-1','verified':False}
            def verify(self,id): return {'verified':self.is_ready,'external_id':id,'url':'https://example.test/actual' if self.is_ready else None}
        p=Queued(); self.assertEqual(self.e.publish_due({'youtube':p},dry_run=False)[0]['status'],'SUBMITTED')
        self.assertEqual(self.e.reconcile_submissions({'youtube':p})[0]['status'],'SUBMITTED')
        self.e.publish_due({'youtube':p},dry_run=False); self.assertEqual(p.calls,1)
        p.is_ready=True
        self.assertEqual(self.e.reconcile_submissions({'youtube':p})[0]['status'],'PUBLISHED')
    def test_expired_claim_recovers_to_unknown(self):
        j=self.ready(); deliveries=self.schedule(j)
        with self.e._tx() as c: c.execute("UPDATE deliveries SET status='IN_FLIGHT',lease_until=?",(self.now-1,))
        self.assertEqual(self.e.recover_expired_leases(),1)
        self.assertEqual(self.e.get_job(j['id'])['deliveries'][0]['status'],'UNKNOWN')
        self.e.reconcile_delivery(deliveries[0]['id'],published=False,verified_evidence='Fixture provider checked; no upload exists')
        self.assertEqual(self.e.get_job(j['id'])['deliveries'][0]['status'],'RETRYING')
    def test_reconciliation_is_bound_to_original_provider_account(self):
        j=self.ready(); self.schedule(j); self.live()
        class Queued:
            account_id='fixture-channel'; verifications=0
            def publish(self,*a,**k): return {'status':'SUBMITTED','external_id':'queue-1','verified':False}
            def verify(self,id):
                self.verifications+=1
                return {'verified':True,'external_id':id,'url':'https://example.test/verified'}
        p=Queued(); self.e.publish_due({'youtube':p},dry_run=False)
        self.assertEqual(self.e.get_job(j['id'])['deliveries'][0]['account_id'],'fixture-channel')
        self.e.configure_publication(True,{'youtube':'changed-channel'},actor='test-human')
        p.account_id='changed-channel'
        self.assertEqual(self.e.reconcile_submissions({'youtube':p})[0]['status'],'SUBMITTED')
        self.assertEqual(p.verifications,0)
        p.account_id='fixture-channel'
        self.assertEqual(self.e.reconcile_submissions({'youtube':p})[0]['status'],'PUBLISHED')
        self.assertEqual(p.verifications,1)
    def test_kill_switch_blocks_render_and_publish(self):
        j=self.ready(); self.schedule(j); self.live(); self.e.kill_switch(True)
        self.assertEqual(self.e.publish_due({'youtube':FakePublisher()},dry_run=False)[0]['status'],'BLOCKED')
        with self.assertRaises(GateError): self.e.reserve_cost('api',0)
    def test_cost_reservations_are_atomic_and_overrun_stops_system(self):
        self.e.approve_budget(1)
        reservation=self.e.reserve_cost('test',0.8)
        with self.assertRaises(GateError): self.e.reserve_cost('test',0.3)
        self.e.settle_cost(reservation,0.9)
        self.assertTrue(self.e.status()['kill_switch'])
        self.assertAlmostEqual(self.e.status()['costs']['spent_usd'],0.9)
        with self.assertRaises(ConflictError): self.e.settle_cost(reservation,0.9)
    def test_budget_ceiling_and_nonfinite_input(self):
        for value in (151,-1,float('nan'),float('inf')):
            with self.assertRaises(GateError): self.e.approve_budget(value)
    def test_metrics_only_after_verified_delivery(self):
        j=self.ready()
        with self.assertRaises(GateError): self.e.record_metrics(j['id'],'youtube',{'views':1},'https://example.test')
        self.schedule(j); self.live(); self.e.publish_due({'youtube':FakePublisher()},dry_run=False)
        self.e.record_metrics(j['id'],'youtube',{'views':42,'completion_rate':None},'https://example.test/provider')
        self.assertEqual(self.e.metrics_report()[0]['values']['views'],42)
        self.assertIsNone(self.e.metrics_report()[0]['values']['completion_rate'])
        self.assertEqual(self.e.get_job(j['id'])['state'],'ANALYZED')
        with self.assertRaises(GateError): self.e.record_metrics(j['id'],'youtube',{'views':-1},'https://example.test')
    def test_audit_log_contains_review_identity(self):
        j=self.review_job(); self.e.review_script(j['id'],'revise',revision=1,actor='owner',feedback='Tighten hook')
        event=self.e.audit_log()[0]
        self.assertEqual(event['actor'],'owner'); self.assertEqual(event['payload']['feedback'],'Tighten hook')
    def test_durable_scripted_stage(self):
        j=self.e.create_job('Draft')
        self.e.set_research(j['id'],[{'url':'https://example.test'}],'Research')
        j=self.e.set_script(j['id'],'Draft text',submit=False)
        self.assertEqual(j['state'],'SCRIPTED')
        self.assertEqual(self.e.submit_review(j['id'])['state'],'HUMAN_REVIEW')
    def test_render_lease_recovery_and_backoff(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1)
        self.add_original_assets(j['id'])
        self.e.start_render(j['id']); self.now+=901
        self.assertEqual(self.e.recover_expired_leases(),1)
        with self.assertRaises(GateError): self.e.start_render(j['id'])
        self.now+=61
        self.assertEqual(self.e.start_render(j['id'])['state'],'RENDERING')
    def test_exact_duplicate_artifact_fails_qc(self):
        first=self.ready(filename='same.mp4'); self.schedule(first)
        with self.assertRaises(GateError): self.ready('Duplicate',filename='same.mp4')
    def test_render_daily_limit(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1)
        self.add_original_assets(j['id'])
        for _ in range(10):
            attempt=self.e.start_render(j['id']); self.e.fail_render(j['id'],render_token=attempt['render_token']); self.now+=61
        with self.assertRaises(GateError): self.e.start_render(j['id'])
    def test_incomplete_manifest_cannot_render(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1)
        self.e.add_asset(j['id'],'visuals',self.asset,'original',provenance='Only visuals')
        with self.assertRaisesRegex(GateError,'incomplete'): self.e.start_render(j['id'])
    def test_active_render_inputs_are_immutable(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1); self.add_original_assets(j['id'])
        self.e.start_render(j['id'])
        with self.assertRaises(GateError): self.e.set_script(j['id'],'Edited mid-render')
        with self.assertRaises(GateError): self.e.add_asset(j['id'],'music',self.asset,'original',provenance='New audio')
        self.assertEqual(self.e.cancel(j['id'])['state'],'CANCELLED')
    def test_stale_render_cannot_complete_or_extend_new_attempt(self):
        j=self.review_job(); self.e.review_script(j['id'],'approve',revision=1); self.add_original_assets(j['id'])
        stale=self.e.start_render(j['id']); self.now+=901; self.e.recover_expired_leases(); self.now+=61
        current=self.e.start_render(j['id']); media=self.path/'late.mp4'; media.write_bytes(b'late-render')
        with self.assertRaises(ConflictError): self.e.finish_render(j['id'],media,revision=1,render_token=stale['render_token'])
        with self.assertRaises(ConflictError): self.e.render_heartbeat(j['id'],render_token=stale['render_token'])
        with self.assertRaises(ConflictError): self.e.fail_render(j['id'],render_token=stale['render_token'])
        self.assertEqual(self.e.get_job(j['id'])['state'],'RENDERING')
        self.e.finish_render(j['id'],media,revision=1,render_token=current['render_token'])
    def test_atomic_revision_compare_and_swap(self):
        j=self.review_job(); self.e.set_script(j['id'],'Second version',expected_revision=1)
        with self.assertRaises(ConflictError): self.e.set_script(j['id'],'Stale second version',expected_revision=1)
        self.assertEqual(self.e.get_job(j['id'])['script'],'Second version')
    def test_bad_media_is_rejected_by_real_probe(self):
        report=inspect_media(self.asset,[])
        self.assertFalse(report['passed']); self.assertFalse(report['checks']['video'])

if __name__=='__main__': unittest.main()
