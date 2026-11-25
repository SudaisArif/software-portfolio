import concurrent.futures
import contextlib
import io
import json
import threading
import unittest

from media_engine import Engine, GateError, ConflictError
import test_engine


class ManualDeliveryTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    review_job = test_engine.EngineTests.review_job
    add_original_assets = test_engine.EngineTests.add_original_assets
    ready = test_engine.EngineTests.ready

    def authorization(self):
        return {'source': 'owner_chat', 'quote': 'Publish these reviewed fixture videos.',
                'reference': 'test-conversation/message-1', 'received_at': self.now}

    def schedule(self, job, offset=0, accounts=None):
        return self.e.schedule_manual(job['id'], self.now + offset, revision=job['revision'],
            artifact_sha256=job['artifact_sha256'], platform_accounts=accounts or {
                'youtube': {'id': 'fixture-channel', 'label': '@fixture'}},
            authorization=self.authorization(), actor='recorder-of-owner-chat')

    def scope(self, delivery):
        return dict(delivery_id=delivery['id'], revision=delivery['revision'],
                    artifact_sha256=delivery['fingerprint'], account_id=delivery['account_id'],
                    account_label='@fixture', actor='assistant-browser-fixture')

    def begin(self, delivery, action='publish_now'):
        return self.e.begin_manual_delivery(**self.scope(delivery), action=action)

    def record(self, delivery, status='queued', **kwargs):
        fields = dict(status=status, receipt_id='buffer-fixture-1', evidence='Fixture Buffer UI observation, screenshot fixture.png', observed_at=self.now)
        fields.update(kwargs)
        return self.e.record_manual_delivery(**self.scope(delivery), **fields)

    def test_authorization_is_scoped_audited_and_does_not_enable_automation_or_spend(self):
        job = self.ready(); deliveries = self.schedule(job)
        event = next(e for e in self.e.audit_log() if e['event'] == 'manual_delivery_authorized')
        self.assertEqual(event['payload']['authorization']['quote'], self.authorization()['quote'])
        self.assertEqual(event['payload']['artifact_sha256'], job['artifact_sha256'])
        self.assertEqual(event['payload']['account'], {'id': 'fixture-channel', 'label': '@fixture'})
        self.assertEqual(event['actor'], 'recorder-of-owner-chat')
        self.assertEqual(deliveries[0]['dispatch_mode'], 'manual')
        self.assertEqual(deliveries, self.schedule(job))
        status = self.e.status()
        self.assertFalse(status['publication_enabled']); self.assertEqual(status['platform_accounts'], {})
        self.assertEqual(status['costs']['approved_usd'], 0)

    def test_script_release_rights_hash_and_identity_still_gate_manual_schedule(self):
        job = self.review_job()
        with self.assertRaises(GateError): self.schedule(job)
        job = self.ready()
        with self.assertRaises(ConflictError): self.schedule({**job, 'revision': job['revision'] + 1})
        with self.assertRaises(ConflictError): self.schedule({**job, 'artifact_sha256': 'wrong'})
        with self.assertRaises(GateError): self.schedule(job, accounts={'youtube': {'id': 'fixture-channel'}})
        with self.e._tx() as c: c.execute('UPDATE jobs SET release_sha256=NULL WHERE id=?', (job['id'],))
        with self.assertRaises(GateError): self.schedule(job)

    def test_manual_and_automatic_share_one_daily_unique_video_limit(self):
        job = self.ready()
        accounts = {p: {'id': p + '-channel', 'label': '@fixture'} for p in ('youtube', 'instagram', 'tiktok')}
        self.assertEqual(len(self.schedule(job, accounts=accounts)), 3)
        other = self.ready('Other')
        with self.assertRaises(GateError): self.e.schedule(other['id'], self.now, ['youtube'])
        with self.assertRaises(GateError): self.schedule(other)
        self.schedule(other, offset=86400)

    def test_automatic_reservation_blocks_manual_schedule(self):
        first = self.ready('Automatic'); self.e.schedule(first['id'], self.now, ['youtube'])
        with self.assertRaises(GateError): self.schedule(self.ready('Manual'))

    def test_manual_rows_never_use_automatic_dispatch_or_reconciliation(self):
        job = self.ready(); delivery = self.schedule(job)[0]
        self.e.configure_publication(True, {'youtube': 'fixture-channel'}, actor='test')
        publisher = test_engine.FakePublisher()
        self.assertEqual(self.e.publish_due({'youtube': publisher}, dry_run=False), [])
        self.begin(delivery); self.record(delivery)
        class VerifyMustNotRun:
            account_id = 'fixture-channel'
            def verify(self, *args): raise AssertionError('manual record must not use API reconciliation')
        self.assertEqual(self.e.reconcile_submissions({'youtube': VerifyMustNotRun()}), [])
        self.assertEqual(publisher.calls, [])

    def test_concurrent_manual_claim_is_exactly_once(self):
        delivery = self.schedule(self.ready())[0]; barrier = threading.Barrier(2)
        def claim(_):
            engine = Engine(self.e.db_path, clock=lambda: self.now); barrier.wait()
            try: engine.begin_manual_delivery(**self.scope(delivery), action='publish_now'); return 'claimed'
            except ConflictError: return 'blocked'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(claim, range(2))), ['claimed', 'blocked'])
        self.assertEqual(self.e.get_job(delivery['job_id'])['deliveries'][0]['attempts'], 1)

    def test_account_revision_hash_mismatch_blocks_claim_and_receipt(self):
        delivery = self.schedule(self.ready())[0]
        for field, value in [('account_id', 'other'), ('account_label', '@other'), ('revision', 99), ('artifact_sha256', 'other')]:
            with self.subTest(field=field), self.assertRaises(ConflictError):
                self.e.begin_manual_delivery(**{**self.scope(delivery), field: value}, action='publish_now')
        self.begin(delivery)
        with self.assertRaises(ConflictError):
            self.e.record_manual_delivery(**{**self.scope(delivery), 'account_id': 'other'}, status='queued',
                                          receipt_id='x', evidence='fixture', observed_at=self.now)

    def test_queued_is_not_published_and_needs_observed_receipt(self):
        delivery = self.schedule(self.ready())[0]
        with self.assertRaises(GateError): self.record(delivery)
        self.begin(delivery)
        with self.assertRaises(GateError): self.record(delivery, receipt_id=None)
        self.assertEqual(self.record(delivery)['status'], 'SUBMITTED')
        self.assertEqual(self.e.get_job(delivery['job_id'])['state'], 'SCHEDULED')
        with self.assertRaises(GateError): self.e.record_metrics(delivery['job_id'], 'youtube', {'views': 1}, 'https://youtube.com')

    def test_verified_publication_needs_real_platform_post_url_and_matching_receipt(self):
        delivery = self.schedule(self.ready())[0]; self.begin(delivery); self.record(delivery)
        for url in ['https://publish.buffer.com', 'https://youtube.com/@fixture', 'https://youtube.com.evil.test/shorts/abcdefghijk', 'https://instagram.com/reel/fixture/']:
            with self.subTest(url=url), self.assertRaises(GateError):
                self.record(delivery, 'published', public_url=url, published_at=self.now)
        with self.assertRaises(ConflictError): self.record(delivery, 'published', receipt_id='wrong', public_url='https://youtube.com/shorts/abcdefghijk', published_at=self.now)
        result = self.record(delivery, 'published', public_url='https://youtube.com/shorts/abcdefghijk', published_at=self.now)
        self.assertEqual(result['status'], 'PUBLISHED'); self.assertEqual(self.e.get_job(delivery['job_id'])['state'], 'PUBLISHED')
        self.assertEqual(result, self.record(delivery, 'published', public_url='https://youtube.com/shorts/abcdefghijk', published_at=self.now))
        with self.assertRaises(ConflictError): self.record(delivery, 'unknown')

    def test_ambiguous_or_expired_manual_submission_cannot_be_retried(self):
        delivery = self.schedule(self.ready())[0]; self.begin(delivery)
        self.now += 1801; self.assertEqual(self.e.recover_expired_leases(), 1)
        self.assertEqual(self.e.get_job(delivery['job_id'])['deliveries'][0]['status'], 'UNKNOWN')
        with self.assertRaises(ConflictError): self.begin(delivery)
        with self.assertRaises(GateError): self.e.reconcile_delivery(delivery['id'], published=False, verified_evidence='No item found')
        self.assertEqual(self.e.publish_due({}, dry_run=False), [])
        self.assertEqual(self.record(delivery)['status'], 'SUBMITTED')

    def test_kill_switch_blocks_send_but_does_not_discard_observed_external_fact(self):
        delivery = self.schedule(self.ready())[0]
        self.e.kill_switch(True)
        with self.assertRaises(GateError): self.begin(delivery)
        self.e.kill_switch(False); self.begin(delivery); self.e.kill_switch(True)
        self.assertEqual(self.record(delivery)['status'], 'SUBMITTED')

    def test_future_clip_can_be_queued_today_but_not_published_early(self):
        first = self.schedule(self.ready('Today'))[0]
        tomorrow = self.schedule(self.ready('Tomorrow'), offset=86400)[0]
        self.begin(first)
        with self.assertRaises(GateError): self.begin(tomorrow)
        self.begin(tomorrow, action='schedule')
        with self.assertRaises(ConflictError): self.record(tomorrow, scheduled_at=self.now)
        self.assertEqual(self.record(tomorrow, scheduled_at=self.now + 86400)['status'], 'SUBMITTED')

    def test_external_daily_limit_violation_is_recorded_truthfully_and_halts_future_actions(self):
        self.schedule(self.ready('Today'))
        tomorrow = self.schedule(self.ready('Tomorrow'), offset=86400)[0]
        self.begin(tomorrow, action='schedule')
        result = self.record(tomorrow, 'published', public_url='https://youtube.com/shorts/abcdefghijk', published_at=self.now)
        self.assertEqual(result['status'], 'PUBLISHED'); self.assertTrue(self.e.status()['kill_switch'])
        self.assertIn('manual_delivery_daily_limit_violation', [event['event'] for event in self.e.audit_log()])

    def test_wrong_provider_day_halts_even_when_otherwise_under_daily_limit(self):
        tomorrow = self.schedule(self.ready(), offset=86400)[0]
        self.begin(tomorrow, action='schedule')
        self.record(tomorrow, 'published', public_url='https://youtube.com/shorts/abcdefghijk', published_at=self.now)
        self.assertTrue(self.e.status()['kill_switch'])
        self.assertIn('manual_delivery_schedule_deviation', [event['event'] for event in self.e.audit_log()])

    def test_edits_cancel_unclaimed_scope_and_claimed_inputs_are_immutable(self):
        job = self.ready(); delivery = self.schedule(job)[0]
        updated = self.e.set_script(job['id'], 'A different exact script')
        with self.assertRaises(GateError): self.begin(delivery)
        with self.e._connect() as c: self.assertEqual(c.execute('SELECT count(*) FROM manual_deliveries').fetchone()[0], 0)
        self.assertIsNone(updated['release_sha256'])
        second = self.ready('Second'); self.begin(self.schedule(second)[0])
        with self.assertRaises(GateError): self.e.set_script(second['id'], 'Cannot edit after send claim')

    def test_cli_manual_commands_record_only_local_scoped_state(self):
        import studio
        job = self.ready()
        request = {'job_id': job['id'], 'when_iso': self.now, 'revision': job['revision'], 'artifact_sha256': job['artifact_sha256'],
                   'platform_accounts': {'youtube': {'id': 'fixture-channel', 'label': '@fixture'}},
                   'authorization': self.authorization(), 'actor': 'fixture-owner-chat-recorder'}
        path = self.path / 'request.json'; path.write_text(json.dumps(request))
        # Use the fixture clock for deterministic authorization and publication days.
        from unittest.mock import patch
        with patch('studio.Engine', return_value=self.e), contextlib.redirect_stdout(io.StringIO()) as output:
            studio.main(['--db', self.e.db_path, 'manual-schedule', str(path)])
        delivery = json.loads(output.getvalue())[0]
        path.write_text(json.dumps({**self.scope(delivery), 'action': 'publish_now'}))
        with patch('studio.Engine', return_value=self.e), contextlib.redirect_stdout(io.StringIO()):
            studio.main(['--db', self.e.db_path, 'manual-begin', str(path)])
        path.write_text(json.dumps({**self.scope(delivery), 'status': 'queued', 'receipt_id': 'buffer-cli-fixture',
                                   'evidence': 'Actual fixture provider receipt', 'observed_at': self.now}))
        with patch('studio.Engine', return_value=self.e), contextlib.redirect_stdout(io.StringIO()) as output:
            studio.main(['--db', self.e.db_path, 'manual-record', str(path)])
        self.assertEqual(json.loads(output.getvalue())['status'], 'SUBMITTED')
        self.assertFalse(self.e.status()['publication_enabled'])


if __name__ == '__main__': unittest.main()
