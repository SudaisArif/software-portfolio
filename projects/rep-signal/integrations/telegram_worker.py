"""Durable owner-only Telegram review inbox. Disconnected unless explicitly configured.

The inbox checkpoint is committed before effects. A request interrupted after it
may have incurred a charge is held for reconciliation, never blindly retried.
Voice and text replies are revision feedback only, including the word 'approve'.
"""
from __future__ import annotations
import contextlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from .http import IntegrationBlocked, NoRedirect, RemoteError, credential
from .openai_api import OpenAI
from .telegram import Telegram

MAX_AUDIO_BYTES = 25_000_000
LEASE_SECONDS = 600
TERMINAL = {"DONE", "IGNORED", "STALE", "FAILED", "NEEDS_RECONCILIATION"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO telegram_settings VALUES('offset','0');
CREATE TABLE IF NOT EXISTS telegram_reviews(
 job_id TEXT NOT NULL, revision INTEGER NOT NULL, chat_id TEXT NOT NULL,
 status TEXT NOT NULL, message_id INTEGER, created_at REAL NOT NULL,
 PRIMARY KEY(job_id,revision,chat_id), UNIQUE(chat_id,message_id));
CREATE TABLE IF NOT EXISTS telegram_updates(
 update_id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL,
 payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NEW',
 lease_until REAL, reservation_id TEXT, transcript TEXT,
 reason TEXT, received_at REAL NOT NULL, updated_at REAL NOT NULL);
"""


class TelegramWorker:
    def __init__(self, engine, state_path=None, bot=None, downloader=None, transcriber=None, clock=time.time):
        self.engine = engine
        self.state_path = Path(state_path or Path(engine.db_path).with_name("telegram.db"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.bot = bot or Telegram()
        self.default_bot = bot is None
        self.downloader = downloader or self._download_voice
        self.transcriber = transcriber or OpenAI().transcribe
        self.default_transcriber = transcriber is None
        self.clock = clock
        with self._db() as c:
            c.executescript(SCHEMA)
        os.chmod(self.state_path, 0o600)

    @contextlib.contextmanager
    def _db(self, write=False):
        c = sqlite3.connect(self.state_path, timeout=20)
        c.row_factory = sqlite3.Row
        try:
            if write:
                c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def _update(self, update_id, **values):
        if not set(values) <= {"status", "lease_until", "reservation_id", "transcript", "reason"}:
            raise ValueError("Invalid inbox update")
        values["updated_at"] = self.clock()
        with self._db(write=True) as c:
            c.execute("UPDATE telegram_updates SET " + ",".join(k+"=?" for k in values) + " WHERE update_id=?", (*values.values(),update_id))

    def status(self):
        with self._db() as c:
            return {"offset":int(c.execute("SELECT value FROM telegram_settings WHERE key='offset'").fetchone()[0]),
                    "counts":dict(c.execute("SELECT status,count(*) FROM telegram_updates GROUP BY status")),
                    "notifications":dict(c.execute("SELECT status,count(*) FROM telegram_reviews GROUP BY status"))}

    def notify_review(self, job_id):
        """Send once per revision. Ambiguous sends are not repeated automatically."""
        job = self.engine.get_job(job_id)
        if job["state"] != "HUMAN_REVIEW":
            raise ValueError("Job is not awaiting script review")
        if self.engine.status()["kill_switch"]:
            raise IntegrationBlocked("Emergency stop is active")
        if self.default_bot:
            if os.getenv("ALLOW_EXTERNAL_REQUESTS")!="true":
                raise IntegrationBlocked("Telegram notifications are not authorized")
            credential("TELEGRAM_BOT_TOKEN")
            credential("TELEGRAM_USER_ID")
        chat = credential("TELEGRAM_CHAT_ID")
        key = (job_id,job["revision"],chat)
        with self._db(write=True) as c:
            existing = c.execute("SELECT * FROM telegram_reviews WHERE job_id=? AND revision=? AND chat_id=?",key).fetchone()
            if existing:
                return {"status":existing["status"],"message_id":existing["message_id"],"already_attempted":True}
            c.execute("INSERT INTO telegram_reviews VALUES(?,?,?,?,?,?)",(*key,"SENDING",None,self.clock()))
        try:
            receipt = self.bot.send_review(job)
            message_id = receipt.get("message_id")
            if not isinstance(message_id,int) or isinstance(message_id,bool) or message_id <= 0:
                raise ValueError("Provider returned no message identity")
            if receipt.get("chat") and str(receipt["chat"].get("id")) != chat:
                raise ValueError("Provider returned a different recipient")
            with self._db(write=True) as c:
                c.execute("UPDATE telegram_reviews SET status='SENT',message_id=? WHERE job_id=? AND revision=? AND chat_id=?",(message_id,*key))
            return {"status":"SENT","message_id":message_id,"revision":job["revision"]}
        except Exception:
            with self._db(write=True) as c:
                c.execute("UPDATE telegram_reviews SET status='UNKNOWN' WHERE job_id=? AND revision=? AND chat_id=?",key)
            raise IntegrationBlocked("Review notification outcome is uncertain; inspect Telegram before any resend") from None

    @staticmethod
    def _owner(update):
        if "callback_query" in update:
            item = update["callback_query"]
            sender = item.get("from",{}).get("id")
            chat = item.get("message",{}).get("chat",{}).get("id")
        else:
            item = update.get("message",{})
            sender = item.get("from",{}).get("id")
            chat = item.get("chat",{}).get("id")
        return str(sender) == credential("TELEGRAM_USER_ID") and str(chat) == credential("TELEGRAM_CHAT_ID")

    def _ingest(self, updates):
        if not isinstance(updates,list) or len(updates)>100:
            raise ValueError("Invalid Telegram update batch")
        with self._db(write=True) as c:
            current = int(c.execute("SELECT value FROM telegram_settings WHERE key='offset'").fetchone()[0])
            for update in updates:
                update_id = update.get("update_id")
                if not isinstance(update_id,int) or isinstance(update_id,bool) or update_id<0:
                    raise ValueError("Invalid Telegram update identity")
                current = max(current,update_id+1)
                owned = self._owner(update)
                callback = update.get("callback_query",{})
                message = update.get("message",{})
                if callback.get("id"):
                    dedupe = "callback:" + str(callback["id"])
                elif message.get("message_id"):
                    dedupe = "message:" + str(message.get("chat",{}).get("id")) + ":" + str(message["message_id"])
                else:
                    dedupe = "update:" + str(update_id)
                payload = json.dumps(update if owned else {},allow_nan=False)
                if len(payload.encode())>100000:
                    owned=False;payload="{}"
                c.execute("INSERT OR IGNORE INTO telegram_updates(update_id,dedupe_key,payload,status,reason,received_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                          (update_id,dedupe,payload,"NEW" if owned else "IGNORED",None if owned else "owner_or_shape_rejected",self.clock(),self.clock()))
            c.execute("UPDATE telegram_settings SET value=? WHERE key='offset'",(str(current),))

    def _mapping(self, message_id):
        with self._db() as c:
            row=c.execute("SELECT * FROM telegram_reviews WHERE chat_id=? AND message_id=? AND status='SENT'",(credential("TELEGRAM_CHAT_ID"),message_id)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _actor(update_id):
        return "telegram-owner:update:" + str(update_id)

    def _effect_exists(self, update_id):
        # This audit marker commits in the SAME transaction as the engine decision.
        # It allows recovery if the worker crashes before committing its own receipt.
        with contextlib.closing(sqlite3.connect(self.engine.db_path)) as c:
            return c.execute("SELECT 1 FROM events WHERE actor=? AND event IN ('script_approve','script_reject','script_revise') LIMIT 1",(self._actor(update_id),)).fetchone() is not None

    def recover_interrupted(self):
        with self._db() as c:
            pending=[r[0] for r in c.execute("SELECT update_id FROM telegram_updates WHERE status='PROCESSING' AND lease_until<?",(self.clock(),))]
        for update_id in pending:
            self._update(update_id,status="DONE" if self._effect_exists(update_id) else "NEEDS_RECONCILIATION",lease_until=None,
                         reason="recovered_committed_decision" if self._effect_exists(update_id) else "interrupted_effect_or_charge_not_retried")
        return len(pending)

    def _decision_proxy(self, update_id):
        worker=self
        class DecisionProxy:
            def review_script(self, job_id, decision, actor=None, revision=None, feedback=""):
                if worker.engine.status()["kill_switch"]:
                    raise IntegrationBlocked("Emergency stop is active")
                if worker._effect_exists(update_id):
                    return worker.engine.get_job(job_id)
                return worker.engine.review_script(job_id,decision,actor=worker._actor(update_id),revision=revision,feedback=feedback)
        return DecisionProxy()

    def _current_review(self, mapping):
        if not mapping:
            return False
        try:
            job=self.engine.get_job(mapping["job_id"])
        except KeyError:
            return False
        return job["state"]=="HUMAN_REVIEW" and job["revision"]==mapping["revision"]

    def _process(self, row, voice_enabled, max_voice_cost):
        update_id=row["update_id"]
        update=json.loads(row["payload"])
        if not self._owner(update):
            self._update(update_id,status="IGNORED",lease_until=None,reason="owner_changed")
            return
        callback=update.get("callback_query")
        if callback:
            mapping=self._mapping(callback.get("message",{}).get("message_id"))
            if not self._current_review(mapping):
                self._update(update_id,status="STALE" if mapping else "IGNORED",lease_until=None,reason="unknown_or_stale_review")
                return
            # Callback must refer to the same mapped message, even if another valid
            # signed callback was copied from a different job or revision.
            parts=str(callback.get("data","")).split(":")
            if len(parts)!=4 or parts[0]!=mapping["job_id"] or parts[1]!=str(mapping["revision"]):
                self._update(update_id,status="IGNORED",lease_until=None,reason="callback_message_binding_mismatch")
                return
            self.bot.accept_callback(update,self._decision_proxy(update_id))
            self._update(update_id,status="DONE",lease_until=None,reason="callback_recorded")
            return
        message=update.get("message",{})
        mapping=self._mapping(message.get("reply_to_message",{}).get("message_id"))
        if not self._current_review(mapping):
            self._update(update_id,status="STALE" if mapping else "IGNORED",lease_until=None,reason="unknown_or_stale_review")
            return
        voice=message.get("voice")
        text=message.get("text")
        if voice:
            if not voice_enabled:
                self._update(update_id,status="WAITING_VOICE",lease_until=None,reason="voice_processing_not_enabled")
                return
            if self.default_transcriber and (os.getenv("ALLOW_EXTERNAL_REQUESTS")!="true" or os.getenv("ALLOW_PAID_APIS")!="true"):
                self._update(update_id,status="WAITING_VOICE",lease_until=None,reason="voice_api_authorization_required")
                return
            if not isinstance(max_voice_cost,(int,float)) or isinstance(max_voice_cost,bool) or not math.isfinite(max_voice_cost) or not 0<max_voice_cost<=5:
                raise ValueError("A positive approved per-voice cost bound up to $5 is required")
            declared_size=voice.get("file_size",0)
            if not isinstance(declared_size,int) or declared_size<0 or declared_size>=MAX_AUDIO_BYTES:
                raise ValueError("Voice note exceeds allowed size")
            file_id=voice.get("file_id")
            if not isinstance(file_id,str) or not file_id or len(file_id)>1024:
                raise ValueError("Invalid voice file identity")
            status=self.engine.status()
            if status["kill_switch"]:
                self._update(update_id,status="WAITING_VOICE",lease_until=None,reason="emergency_stop")
                return
            costs=status["costs"]
            if costs["approved_usd"]-costs["spent_usd"]-costs["reserved_usd"]<max_voice_cost:
                self._update(update_id,status="WAITING_VOICE",lease_until=None,reason="voice_budget_authorization_required")
                return
            audio_dir=self.state_path.parent/"telegram-audio"
            audio_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
            target=audio_dir/(str(update_id)+".ogg")
            path=Path(self.downloader(file_id,target))
            if not path.is_file() or path.stat().st_size>=MAX_AUDIO_BYTES:
                raise ValueError("Downloaded voice file is missing or oversized")
            reservation=self.engine.reserve_cost("openai:telegram-voice",max_voice_cost)
            self._update(update_id,reservation_id=reservation,reason="transcription_started")
            result=self.transcriber(path)
            text=result.get("text") if isinstance(result,dict) else result
            if not isinstance(text,str) or not text.strip() or len(text)>10000:
                raise ValueError("Voice transcript missing or too long")
            self._update(update_id,transcript=text,reason="transcription_completed")
            text="Voice note transcript (verify accuracy): " + text
        elif isinstance(text,str) and text.strip() and len(text)<=10000:
            text="Telegram reply: " + text
        else:
            self._update(update_id,status="IGNORED",lease_until=None,reason="unsupported_message")
            return
        if not self._current_review(mapping):
            self._update(update_id,status="STALE",lease_until=None,reason="revision_changed_during_feedback")
            return
        self._decision_proxy(update_id).review_script(mapping["job_id"],"revise",revision=mapping["revision"],feedback=text)
        self._update(update_id,status="DONE",lease_until=None,reason="revision_feedback_recorded")

    def poll_once(self, voice_enabled=False, max_voice_cost=None, stop_requested=None):
        """Fetch, durably checkpoint, then process. Returns no secrets or transcripts."""
        stop_requested=stop_requested or (lambda:False)
        if stop_requested():return {"stopped":True,"updates":[],**self.status()}
        if self.engine.status()["kill_switch"]:return {"paused":True,"updates":[],**self.status()}
        self.recover_interrupted()
        offset=self.status()["offset"]
        updates=self.bot.call("getUpdates",{"offset":offset,"limit":100,"timeout":0,"allowed_updates":["message","callback_query"]})
        self._ingest(updates)
        with self._db() as c:
            ids=[r[0] for r in c.execute("SELECT update_id FROM telegram_updates WHERE status IN ('NEW','WAITING_VOICE') ORDER BY update_id")]
        outcomes=[]
        for update_id in ids:
            if stop_requested() or self.engine.status()["kill_switch"]:break
            with self._db(write=True) as c:
                row=c.execute("SELECT * FROM telegram_updates WHERE update_id=?",(update_id,)).fetchone()
                if row["status"] not in {"NEW","WAITING_VOICE"}:
                    continue
                c.execute("UPDATE telegram_updates SET status='PROCESSING',lease_until=?,updated_at=? WHERE update_id=?",(self.clock()+LEASE_SECONDS,self.clock(),update_id))
                row=dict(row)
            try:
                self._process(row,voice_enabled,max_voice_cost)
            except Exception as exc:
                if self._effect_exists(update_id):
                    self._update(update_id,status="DONE",lease_until=None,reason="decision_committed_acknowledgment_unavailable")
                else:
                    with self._db() as c:
                        charged=c.execute("SELECT reservation_id FROM telegram_updates WHERE update_id=?",(update_id,)).fetchone()[0]
                    if charged:self._update(update_id,status="NEEDS_RECONCILIATION",lease_until=None,reason=type(exc).__name__)
                    elif self.engine.status()["kill_switch"]:self._update(update_id,status="NEW",lease_until=None,reason="emergency_stop_before_decision")
                    else:self._update(update_id,status="FAILED",lease_until=None,reason=type(exc).__name__)
            with self._db() as c:
                final=c.execute("SELECT status,reason FROM telegram_updates WHERE update_id=?",(update_id,)).fetchone()
                outcomes.append({"update_id":update_id,"status":final["status"],"reason":final["reason"]})
        return {"updates":outcomes,"paused":self.engine.status()["kill_switch"],"stopped":bool(stop_requested()),**self.status()}

    def _download_voice(self, file_id, destination):
        if os.getenv("ALLOW_EXTERNAL_REQUESTS")!="true":
            raise IntegrationBlocked("Telegram file download is disabled")
        record=self.bot.call("getFile",{"file_id":file_id})
        path=record.get("file_path","")
        components=PurePosixPath(path)
        if not path or components.is_absolute() or ".." in components.parts or "\\" in path or ":" in path or "?" in path or "#" in path:
            raise ValueError("Unsafe Telegram file path")
        if record.get("file_id",file_id)!=file_id or not isinstance(record.get("file_size",0),int) or record.get("file_size",0)>=MAX_AUDIO_BYTES:
            raise ValueError("Telegram file identity or size mismatch")
        url="https://api.telegram.org/file/bot"+credential("TELEGRAM_BOT_TOKEN")+"/"+urllib.parse.quote(path,safe="/")
        destination=Path(destination)
        temporary=destination.with_suffix(destination.suffix+".part")
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,method="GET"),timeout=45) as response:
                declared=response.headers.get("Content-Length")
                if declared and (not declared.isdigit() or int(declared)>=MAX_AUDIO_BYTES):
                    raise ValueError("Voice download exceeds size limit")
                fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,"wb") as output:
                    total=0
                    while True:
                        chunk=response.read(min(65536,MAX_AUDIO_BYTES-total))
                        if not chunk:break
                        total+=len(chunk)
                        if total>=MAX_AUDIO_BYTES:raise ValueError("Voice download exceeds size limit")
                        output.write(chunk)
                if not total:raise ValueError("Empty voice download")
            os.replace(temporary,destination)
            return destination
        except (urllib.error.URLError,urllib.error.HTTPError,OSError,TimeoutError,RemoteError):
            raise IntegrationBlocked("Telegram file download failed; no request details logged") from None
        finally:
            if temporary.exists():temporary.unlink()


def notify_review(engine, job_id, **kwargs):
    return TelegramWorker(engine,**kwargs).notify_review(job_id)
