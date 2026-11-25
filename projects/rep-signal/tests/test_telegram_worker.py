"""Inbox/deduplication tests use injected providers; no requests or messages leave the host."""
import copy
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from integrations.telegram import Telegram
from integrations.telegram_worker import TelegramWorker,LEASE_SECONDS
from media_engine import Engine


class FakeTransport:
    def __init__(self):self.calls=[];self.updates=[];self.message=40
    def request(self,method,url,**kwargs):
        self.calls.append((url.rsplit("/",1)[-1],kwargs.get("payload")))
        operation=url.rsplit("/",1)[-1]
        if operation=="sendMessage":
            self.message+=1;return {"ok":True,"result":{"message_id":self.message,"chat":{"id":123}}}
        if operation=="getUpdates":return {"ok":True,"result":copy.deepcopy(self.updates)}
        return {"ok":True,"result":True}


class TelegramWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{"TELEGRAM_BOT_TOKEN":"test-token","TELEGRAM_CHAT_ID":"123","TELEGRAM_USER_ID":"456"},clear=True)
        env.start();self.addCleanup(env.stop)
        self.engine=Engine(self.root/"engine.db")
        job=self.engine.create_job("Inbox fixture",sources=[{"url":"https://example.org/fixture"}])
        self.job=self.engine.set_script(job["id"],"A fixture for private review.")
        self.transport=FakeTransport();self.bot=Telegram(self.transport)
        self.now=1000
        self.downloads=[];self.transcriptions=[]
        def download(file_id,target):
            self.downloads.append(file_id);target.write_bytes(b"test-audio");return target
        def transcribe(path):
            self.transcriptions.append(path);return {"text":"Approve the script. Make the opening more specific."}
        self.worker=TelegramWorker(self.engine,self.root/"inbox.db",bot=self.bot,downloader=download,transcriber=transcribe,clock=lambda:self.now)
        self.notification=self.worker.notify_review(self.job["id"])

    def callback(self,update_id=1,action="a"):
        return {"update_id":update_id,"callback_query":{"id":"callback-"+str(update_id),"from":{"id":456},"message":{"message_id":self.notification["message_id"],"chat":{"id":123}},"data":self.bot.sign(self.job["id"],self.job["revision"],action)}}

    def voice(self,update_id=2):
        return {"update_id":update_id,"message":{"message_id":100+update_id,"from":{"id":456},"chat":{"id":123},"reply_to_message":{"message_id":self.notification["message_id"]},"voice":{"file_id":"voice-fixture","file_size":10}}}

    def test_notification_is_once_per_revision_and_not_approval(self):
        repeated=self.worker.notify_review(self.job["id"])
        self.assertTrue(repeated["already_attempted"])
        self.assertEqual(sum(method=="sendMessage" for method,_ in self.transport.calls),1)
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")

    def test_wrong_owner_and_unknown_reply_have_no_effect(self):
        wrong=self.callback();wrong["callback_query"]["from"]["id"]=999
        unknown=self.voice();unknown["message"]["reply_to_message"]["message_id"]=999
        self.transport.updates=[wrong,unknown]
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"IGNORED":2})
        self.assertEqual(self.downloads,[])
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")

    def test_signed_callback_and_update_replay_apply_once(self):
        self.transport.updates=[self.callback()]
        first=self.worker.poll_once();second=self.worker.poll_once()
        self.assertEqual(first["counts"],{"DONE":1});self.assertEqual(second["updates"],[])
        approvals=[e for e in self.engine.audit_log() if e["event"]=="script_approve"]
        self.assertEqual(len(approvals),1)
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"APPROVED")

    def test_duplicate_callback_id_in_new_update_does_not_apply_twice(self):
        a=self.callback(action="v");b=copy.deepcopy(a);b["update_id"]=2
        self.transport.updates=[a,b]
        self.worker.poll_once()
        changes=[e for e in self.engine.audit_log() if e["event"]=="script_revise"]
        self.assertEqual(len(changes),1)
        self.assertEqual(self.worker.status()["offset"],3)

    def test_voice_waits_for_enable_then_is_only_feedback_and_spends_once(self):
        self.transport.updates=[self.voice()]
        result=self.worker.poll_once()
        self.assertEqual(result["counts"],{"WAITING_VOICE":1});self.assertEqual(self.downloads,[])
        self.assertEqual(result["offset"],3)
        self.engine.approve_budget(1,actor="test-fixture")
        self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(len(self.transcriptions),1)
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.assertIsNone(self.engine.get_job(self.job["id"])["approved_revision"])
        self.assertAlmostEqual(self.engine.status()["costs"]["reserved_usd"],.1)
        self.assertEqual(self.engine.status()["costs"]["spent_usd"],0)
        feedback=[e for e in self.engine.audit_log() if e["event"]=="script_revise"]
        self.assertIn("Approve the script",feedback[0]["payload"]["feedback"])

    def test_stale_voice_never_downloads_or_charges(self):
        self.transport.updates=[self.voice()]
        self.engine.set_script(self.job["id"],"The next script revision.")
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"STALE":1})
        self.assertEqual(self.downloads,[])
        self.assertEqual(self.engine.status()["costs"]["reserved_usd"],0)

    def test_voice_with_no_approved_budget_remains_queued(self):
        self.transport.updates=[self.voice()]
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"WAITING_VOICE":1})
        self.assertEqual(self.downloads,[])
        self.engine.approve_budget(1,actor="test-fixture")
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"DONE":1})

    def test_revision_change_during_transcription_does_not_apply_old_feedback(self):
        self.engine.approve_budget(1,actor="test-fixture")
        def changed(path):
            self.engine.set_script(self.job["id"],"A new revision from the dashboard.")
            return "This belongs to the old version."
        self.worker.transcriber=changed;self.transport.updates=[self.voice()]
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"STALE":1})
        self.assertEqual([e for e in self.engine.audit_log() if e["event"]=="script_revise"],[])

    def test_text_approve_is_feedback_only(self):
        update=self.voice();update["message"].pop("voice");update["message"]["text"]="approve"
        self.transport.updates=[update];self.worker.poll_once()
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.assertEqual(self.transcriptions,[])

    def test_crash_after_engine_decision_recovers_without_reapplying(self):
        original=self.bot.accept_callback
        def crash(update,engine):
            original(update,engine)
            raise SystemExit("simulated process death")
        self.bot.accept_callback=crash;self.transport.updates=[self.callback(action="v")]
        with self.assertRaises(SystemExit):self.worker.poll_once()
        self.assertEqual(self.worker.status()["offset"],2)
        self.now+=LEASE_SECONDS+1;self.bot.accept_callback=original
        result=self.worker.poll_once()
        self.assertEqual(result["counts"],{"DONE":1})
        self.assertEqual(len([e for e in self.engine.audit_log() if e["event"]=="script_revise"]),1)

    def test_crash_during_paid_transcription_does_not_charge_or_transcribe_twice(self):
        self.engine.approve_budget(1,actor="test-fixture")
        def crash(path):
            self.transcriptions.append(path)
            raise SystemExit("simulated process death after request")
        self.worker.transcriber=crash;self.transport.updates=[self.voice()]
        with self.assertRaises(SystemExit):self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(self.worker.status()["offset"],3)
        self.now+=LEASE_SECONDS+1
        result=self.worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"NEEDS_RECONCILIATION":1})
        self.assertEqual(len(self.transcriptions),1)
        self.assertAlmostEqual(self.engine.status()["costs"]["reserved_usd"],.1)

    def test_tampered_signature_and_cross_message_binding_are_rejected(self):
        update=self.callback();update["callback_query"]["data"]=update["callback_query"]["data"][:-1]+"x"
        self.transport.updates=[update];self.worker.poll_once()
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.assertEqual(self.worker.status()["counts"],{"FAILED":1})

    def test_valid_signature_for_another_job_cannot_use_this_review_message(self):
        other=self.engine.create_job("Other fixture",sources=[{"url":"https://example.org/other"}])
        other=self.engine.set_script(other["id"],"Another draft.")
        update=self.callback();update["callback_query"]["data"]=self.bot.sign(other["id"],other["revision"],"a")
        self.transport.updates=[update];self.worker.poll_once()
        self.assertEqual(self.worker.status()["counts"],{"IGNORED":1})
        self.assertEqual(self.engine.get_job(other["id"])["state"],"HUMAN_REVIEW")

    def test_unconfigured_default_bot_does_not_claim_notification(self):
        worker=TelegramWorker(self.engine,self.root/"disconnected.db")
        from integrations.http import IntegrationBlocked
        with self.assertRaises(IntegrationBlocked):worker.notify_review(self.job["id"])
        self.assertEqual(worker.status()["notifications"],{})

    def test_default_voice_is_not_used_without_api_authorization(self):
        worker=TelegramWorker(self.engine,self.root/"inbox.db",bot=self.bot,clock=lambda:self.now)
        self.transport.updates=[self.voice()]
        result=worker.poll_once(voice_enabled=True,max_voice_cost=.1)
        self.assertEqual(result["counts"],{"WAITING_VOICE":1})
        self.assertEqual(self.engine.status()["costs"]["reserved_usd"],0)

    def test_downloader_rejects_traversal_before_network(self):
        self.bot.call=lambda method,payload:{"file_path":"../../secrets","file_id":"file","file_size":2}
        with patch.dict(os.environ,{"ALLOW_EXTERNAL_REQUESTS":"true"}), patch("urllib.request.build_opener") as opener:
            with self.assertRaises(ValueError):self.worker._download_voice("file",self.root/"audio.ogg")
            opener.assert_not_called()


if __name__=="__main__":unittest.main()
