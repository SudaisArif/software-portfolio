import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from integrations.buffer import Buffer
from integrations.elevenlabs import ElevenLabs
from integrations.http import Transport, IntegrationBlocked, RemoteError
from integrations.openai_api import OpenAI
from integrations.publishing import BufferPublisher
from integrations.storage import ObjectStorage
from integrations.telegram import Telegram
from media_engine import Engine, GateError, RetryablePublishError
from pipeline import generate, editorial_check, RESULT_SCHEMA


class FakeTransport:
    def __init__(self,result):self.result=result;self.calls=[]
    def request(self,*args,**kwargs):self.calls.append((args,kwargs));return self.result


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"OPENAI_API_KEY":"test-placeholder","OPENAI_MODEL":"gpt-5.4-mini","ELEVENLABS_API_KEY":"test-placeholder","ELEVENLABS_VOICE_ID":"testvoice","BUFFER_API_KEY":"test-placeholder","BUFFER_YOUTUBE_CHANNEL_ID":"approved-channel","TELEGRAM_BOT_TOKEN":"test-placeholder","TELEGRAM_CHAT_ID":"123","TELEGRAM_USER_ID":"456"},clear=True);self.env.start();self.addCleanup(self.env.stop)

    def test_live_transport_disabled_by_default(self):
        with self.assertRaises(IntegrationBlocked):Transport().request("GET","https://api.openai.com/v1/models")

    def test_paid_network_and_unknown_hosts_blocked(self):
        with patch.dict(os.environ,{"ALLOW_EXTERNAL_REQUESTS":"true"}):
            with self.assertRaises(IntegrationBlocked):Transport().request("POST","https://api.openai.com/v1/responses",paid=True)
            with self.assertRaises(IntegrationBlocked):Transport().request("GET","https://attacker.invalid/")

    def test_responses_schema_and_refusal(self):
        transport=FakeTransport({"status":"completed","id":"response-fixture","output":[{"content":[{"type":"output_text","text":'{"ok":true}'}]}],"usage":{"input_tokens":3,"output_tokens":4}})
        value=OpenAI(transport).structured("test",{},RESULT_SCHEMA)
        self.assertTrue(value["data"]["ok"]);self.assertTrue(transport.calls[0][1]["paid"])
        self.assertFalse(transport.calls[0][1]["payload"]["store"])
        transport.result={"status":"completed","output":[{"content":[{"type":"refusal","refusal":"no"}]}]}
        with self.assertRaises(IntegrationBlocked):OpenAI(transport).structured("test",{},RESULT_SCHEMA)
        transport.result={"status":"incomplete","output":[]}
        with self.assertRaises(IntegrationBlocked):OpenAI(transport).structured("test",{},RESULT_SCHEMA)

    def test_narration_requires_audio_and_alignment(self):
        alignment={"characters":["H","i"],"character_start_times_seconds":[0,.1],"character_end_times_seconds":[.1,.2]}
        transport=FakeTransport({"audio_base64":base64.b64encode(b"audio-fixture").decode(),"alignment":alignment})
        audio,timing=ElevenLabs(transport).synthesize("Hi");self.assertEqual(audio,b"audio-fixture")
        alignment["character_start_times_seconds"]=[.2,.1]
        with self.assertRaises(IntegrationBlocked):ElevenLabs(transport).synthesize("Hi")

    def test_buffer_pending_is_not_published_and_receipt_identity_checked(self):
        transport=FakeTransport({"data":{"post":{"id":"post-1","status":"scheduled","sentAt":None,"externalLink":None}}})
        self.assertFalse(Buffer(transport).verify("post-1")["verified"])
        transport.result["data"]["post"].update(status="sent",sentAt="2026-11-13T12:00:00Z",externalLink="https://youtube.com/shorts/fixture")
        self.assertTrue(Buffer(transport).verify("post-1")["verified"])
        with self.assertRaises(RemoteError):Buffer(transport).verify("different-post")

    def test_buffer_creation_disabled_and_metadata_platform_specific(self):
        transport=FakeTransport({})
        with self.assertRaises(IntegrationBlocked):Buffer(transport).create({})
        self.assertEqual(transport.calls,[])
        for platform in ("youtube","instagram","tiktok"):
            payload=Buffer.payload(platform,"channel","Title","Caption","https://cdn.example/video.mp4","2026-11-14T18:00:00-05:00")
            self.assertTrue(payload["metadata"][platform]["isAiGenerated"])
        with self.assertRaises(ValueError):Buffer.payload("youtube","channel","Title","Caption","http://localhost/file","date")

    def test_publisher_requires_verified_unexpired_storage_and_account(self):
        publisher=BufferPublisher("youtube",{})
        self.assertEqual(publisher.account_id,"approved-channel")
        with self.assertRaises(RetryablePublishError):publisher.publish({"artifact_sha256":"abc"},"claim")
        publisher.media_urls={"abc":{"sha256":"abc","expires_at":time.time()-1,"storage_verified":True,"url":"https://cdn.example/video.mp4"}}
        with self.assertRaises(RetryablePublishError):publisher.publish({"artifact_sha256":"abc"},"claim")

    def test_provider_failed_receipt_is_actionable(self):
        class Failed:
            def verify(self,remote_id):return {"verified":False,"has_error":True,"provider_status":"error"}
        self.assertEqual(BufferPublisher("youtube",{},Failed()).verify("id")["status"],"FAILED")

    def test_telegram_callback_binds_sender_signature_and_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/"test.db")
            job=engine.create_job("Fixture",sources=[{"url":"https://example.org/study"}]);job=engine.set_script(job["id"],"An isolated test script.")
            bot=Telegram(FakeTransport({"ok":True,"result":True}))
            callback=bot.sign(job["id"],job["revision"],"a");self.assertLessEqual(len(callback.encode()),64)
            update={"callback_query":{"id":"query-fixture","from":{"id":456},"message":{"chat":{"id":123}},"data":callback}}
            update["callback_query"]["from"]["id"]=0
            with self.assertRaises(IntegrationBlocked):bot.accept_callback(update,engine)
            update["callback_query"]["from"]["id"]=456
            bot.accept_callback(update,engine);self.assertEqual(engine.get_job(job["id"])["state"],"APPROVED")
            with self.assertRaises(GateError):bot.accept_callback(update,engine)

    def test_telegram_review_message_is_not_approval(self):
        transport=FakeTransport({"ok":True,"result":{"message_id":4}})
        Telegram(transport).send_review({"id":"0"*32,"revision":1,"title":"Title","script":"Draft"})
        payload=transport.calls[0][1]["payload"]
        self.assertEqual(len(payload["reply_markup"]["inline_keyboard"][0]),3)
        self.assertIn("does not authorize publishing",payload["text"])

    def test_storage_checks_content_hash_and_remote_metadata(self):
        class Storage:
            def put_object(self,**kw):self.data=kw["Body"].read();self.meta=kw["Metadata"]
            def head_object(self,**kw):return {"Metadata":self.meta,"ContentLength":len(self.data)}
            def generate_presigned_url(self,*args,**kw):return "https://storage.example/signed-fixture"
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.mp4";path.write_bytes(b"synthetic-media-fixture");digest=hashlib.sha256(path.read_bytes()).hexdigest()
            adapter=ObjectStorage(Storage())
            with self.assertRaises(ValueError):adapter.upload_verified(path,"wrong","bucket")
            result=adapter.upload_verified(path,digest,"bucket")
            self.assertTrue(result["storage_verified"]);self.assertIn(digest,result["key"])

    def test_generation_stops_at_review_and_does_not_fabricate_spend(self):
        script="After class, the gym can feel far away. Choose a time and a place for the next session. Put your bag by the door. Start with the warm-up you planned. It is an experiment, and you can adjust it when the day changes."
        class Agent:
            def structured(self,*args):return {"data":{"title":"Specific start","script":script,"reasoning":"test fixture","decision":"accept","source_urls":["https://example.org/study"],"uncertainties":["Fixture only"]},"usage":{"input_tokens":5,"output_tokens":8}}
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/"test.db");engine.approve_budget(1,actor="test-fixture")
            result=generate(engine,{"sources":[{"url":"https://example.org/study"}],"evidence":"Explicit test evidence"},.1,Agent())
            self.assertTrue(result["accepted"]);self.assertEqual(result["job"]["state"],"HUMAN_REVIEW")
            self.assertAlmostEqual(engine.status()["costs"]["reserved_usd"],.5);self.assertEqual(engine.status()["costs"]["spent_usd"],0)
            with self.assertRaises(ValueError):generate(engine,{"sources":[{"url":"https://example.org/study"}],"evidence":"a"*13000},.1,Agent())

    def test_editorial_rejects_cliches_and_near_duplicates(self):
        script="No excuses. "*30
        self.assertFalse(editorial_check(script,[{"url":"https://example.org"}])["passed"])
        original="A specific time and place can give a training session somewhere to start. "*4
        self.assertFalse(editorial_check(original,[{"url":"https://example.org"}],[original])["passed"])


if __name__=="__main__":unittest.main()
