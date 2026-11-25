"""Foreground polling tests: real local inbox, mocked bot transport, no live requests."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import Mock,patch

from integrations.http import IntegrationBlocked,Transport
from integrations.telegram import Telegram
from integrations.telegram_service import run_telegram_worker,worker_lock
from integrations.telegram_worker import TelegramWorker
from media_engine import Engine

TRANSPORT_REQUEST=Transport.request


class FakeTransport:
    def __init__(self):self.calls=[];self.updates=[];self.on_get=None
    def request(self,method,url,**kwargs):
        operation=url.rsplit("/",1)[-1];self.calls.append(operation)
        if operation=="sendMessage":return {"ok":True,"result":{"message_id":40,"chat":{"id":123}}}
        if operation=="getUpdates":
            if self.on_get:self.on_get()
            return {"ok":True,"result":copy.deepcopy(self.updates)}
        return {"ok":True,"result":True}


class CountedStop:
    def __init__(self,after):self.after=after;self.waits=[];self.stopped=False
    def is_set(self):return self.stopped
    def set(self):self.stopped=True
    def wait(self,seconds):
        self.waits.append(seconds)
        if len(self.waits)>=self.after:self.stopped=True
        return self.stopped


class TelegramServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        env=patch.dict(os.environ,{"ALLOW_EXTERNAL_REQUESTS":"true","ALLOW_PAID_APIS":"true","ALLOW_PUBLISHING":"true","TELEGRAM_BOT_TOKEN":"offline-fixture-token","TELEGRAM_CHAT_ID":"123","TELEGRAM_USER_ID":"456"},clear=True)
        env.start();self.addCleanup(env.stop)
        guard=patch("integrations.http.Transport.request",side_effect=AssertionError("Live transport forbidden in tests"));guard.start();self.addCleanup(guard.stop)
        self.engine=Engine(self.path/"media.db")
        job=self.engine.create_job("Private fixture",sources=[{"url":"https://example.org/fixture"}])
        self.job=self.engine.set_script(job["id"],"Only the confirmed owner may review this fixture.")
        self.transport=FakeTransport();self.bot=Telegram(self.transport)
        self.download=Mock(side_effect=AssertionError("Voice download forbidden"))
        self.transcribe=Mock(side_effect=AssertionError("Paid transcription forbidden"))
        self.worker=TelegramWorker(self.engine,self.path/"telegram.db",bot=self.bot,downloader=self.download,transcriber=self.transcribe)
        self.worker.notify_review(self.job["id"])
        self.transport.calls.clear();self.events=[]

    def run_service(self,**kwargs):
        return run_telegram_worker(self.engine,worker=self.worker,emit=self.events.append,handle_signals=False,**kwargs)

    def callback(self):
        return {"update_id":1,"callback_query":{"id":"fixture-callback","from":{"id":456},"message":{"message_id":40,"chat":{"id":123}},"data":self.bot.sign(self.job["id"],1,"a")}}

    def test_one_cycle_accepts_only_existing_owner_signed_review(self):
        self.transport.updates=[self.callback()]
        result=self.run_service(once=True)
        self.assertEqual(result["cycles"],1);self.assertEqual(result["exit_code"],0)
        self.assertEqual(self.transport.calls,["getUpdates","answerCallbackQuery"])
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"APPROVED")
        self.assertFalse(self.engine.status()["publication_enabled"])
        logs=json.dumps(self.events)
        self.assertNotIn("fixture-callback",logs);self.assertNotIn(self.job["id"],logs)
        self.assertNotIn("offline-fixture-token",logs)

    def test_voice_stays_waiting_without_download_charge_or_flag_changes(self):
        self.engine.approve_budget(1,actor="offline-test")
        self.transport.updates=[{"update_id":1,"message":{"message_id":50,"from":{"id":456},"chat":{"id":123},"reply_to_message":{"message_id":40},"voice":{"file_id":"private-fixture-file","file_size":10}}}]
        flags=[]
        self.transport.on_get=lambda:flags.append((os.environ["ALLOW_PAID_APIS"],os.environ["ALLOW_PUBLISHING"]))
        self.run_service(once=True)
        self.assertEqual(flags,[("false","false")])
        self.assertEqual(self.worker.status()["counts"],{"WAITING_VOICE":1})
        self.download.assert_not_called();self.transcribe.assert_not_called()
        self.assertEqual(self.engine.status()["costs"]["reserved_usd"],0)
        self.assertEqual(self.engine.status()["costs"]["spent_usd"],0)
        self.assertEqual(os.environ["ALLOW_PAID_APIS"],"true")
        self.assertEqual(os.environ["ALLOW_PUBLISHING"],"true")

    def test_idle_loop_waits_and_emits_no_repeated_idle_records(self):
        stop=CountedStop(after=3)
        result=self.run_service(stop_event=stop)
        self.assertEqual(result["cycles"],3);self.assertEqual(stop.waits,[10,10,10])
        self.assertEqual(self.transport.calls,["getUpdates"]*3)
        self.assertEqual([e["state"] for e in self.events],["starting","idle"])

    def test_existing_kill_switch_prevents_fetching_or_decisions(self):
        self.engine.kill_switch(True,actor="offline-test")
        self.transport.updates=[self.callback()]
        self.run_service(once=True)
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.assertEqual(self.events[-1]["state"],"paused_kill_switch")

    def test_kill_during_fetch_retains_queued_review_until_resume(self):
        self.transport.updates=[self.callback()]
        self.transport.on_get=lambda:self.engine.kill_switch(True,actor="offline-test")
        self.run_service(once=True)
        self.assertEqual(self.transport.calls,["getUpdates"])
        self.assertEqual(self.worker.status()["counts"],{"NEW":1})
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.engine.kill_switch(False,actor="offline-test");self.transport.on_get=None
        self.run_service(once=True)
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"APPROVED")

    def test_stop_during_fetch_checkpoints_without_applying_callback(self):
        stop=threading.Event();self.transport.updates=[self.callback()];self.transport.on_get=stop.set
        result=self.run_service(stop_event=stop)
        self.assertEqual(result["cycles"],1)
        self.assertEqual(self.worker.status()["counts"],{"NEW":1})
        self.assertEqual(self.engine.get_job(self.job["id"])["state"],"HUMAN_REVIEW")
        self.assertEqual(self.transport.calls,["getUpdates"])

    def test_errors_are_redacted_and_throttled_without_messages(self):
        self.worker.poll_once=Mock(side_effect=RuntimeError("PRIVATE-TOKEN private payload"))
        result=self.run_service(stop_event=CountedStop(after=3))
        self.assertEqual(result["errors"],3)
        self.assertEqual([e["state"] for e in self.events],["starting","error"])
        self.assertNotIn("PRIVATE-TOKEN",json.dumps(self.events))
        self.assertEqual(self.transport.calls,[])
        result=self.run_service(once=True);self.assertEqual(result["exit_code"],1)

    def test_http_error_closes_response_without_exposing_provider_details(self):
        error=urllib.error.HTTPError("https://example.test/PRIVATE-TOKEN",401,"PRIVATE-PROVIDER-TEXT",{},None)
        opener=Mock();opener.open.side_effect=error
        self.worker.bot=Telegram()
        with patch.object(Transport,"request",TRANSPORT_REQUEST),patch("integrations.http.urllib.request.build_opener",return_value=opener):
            result=self.run_service(once=True)
        self.assertEqual(result["exit_code"],1);self.assertTrue(error.closed)
        self.assertNotIn("PRIVATE",json.dumps(self.events))

    def test_signal_handler_requests_stop_and_restores_original_handlers(self):
        installed={};registrations=[]
        original={signal.SIGINT:object(),signal.SIGTERM:object()}
        def register(signum,handler):installed[signum]=handler;registrations.append((signum,handler))
        self.transport.on_get=lambda:installed[signal.SIGTERM](signal.SIGTERM,None)
        with patch("integrations.telegram_service.signal.getsignal",side_effect=lambda sig:original[sig]),patch("integrations.telegram_service.signal.signal",side_effect=register):
            result=run_telegram_worker(self.engine,worker=self.worker,emit=self.events.append)
        self.assertEqual(result["cycles"],1)
        self.assertEqual(installed,original)
        self.assertEqual(len(registrations),4)
        self.assertEqual(self.transport.calls,["getUpdates"])

    def test_concurrent_worker_and_unsafe_lock_are_rejected(self):
        path=self.path/"telegram-worker.lock"
        with worker_lock(path):
            with self.assertRaisesRegex(IntegrationBlocked,"already holds"):self.run_service(once=True)
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(path.read_text(),"")
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        path.unlink();target=self.path/"unrelated";target.write_text("keep");path.symlink_to(target)
        with self.assertRaises(IntegrationBlocked):self.run_service(once=True)
        self.assertEqual(target.read_text(),"keep")

    def test_invalid_interval_or_missing_authorization_cannot_poll(self):
        for interval in (0,9,3601,True,float("nan")):
            with self.subTest(interval=interval),self.assertRaises(ValueError):self.run_service(interval=interval,once=True)
        with patch.dict(os.environ,{"ALLOW_EXTERNAL_REQUESTS":"false"}),self.assertRaises(IntegrationBlocked):self.run_service(once=True)
        with patch.dict(os.environ,{"TELEGRAM_USER_ID":""}),self.assertRaises(IntegrationBlocked):self.run_service(once=True)
        self.assertEqual(self.transport.calls,[])

    def test_cli_worker_is_explicit_and_has_no_voice_option(self):
        import studio
        with patch("integrations.telegram_service.run_telegram_worker",return_value={"exit_code":0,"state":"stopped"}) as run,contextlib.redirect_stdout(io.StringIO()):
            studio.main(["--db",str(self.path/"media.db"),"telegram-worker","--live","--once","--interval","12"])
        self.assertEqual(run.call_args.kwargs,{"interval":12.0,"once":True})
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):studio.main(["telegram-worker","--live","--voice-enabled"])


if __name__=="__main__":unittest.main()
