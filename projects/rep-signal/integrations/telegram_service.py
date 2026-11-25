"""Foreground, single-process private review polling. Never generates or publishes media."""
from __future__ import annotations
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import stat
import threading

from .http import IntegrationBlocked,credential
from .telegram_worker import TelegramWorker


@contextlib.contextmanager
def worker_lock(path):
    """Keep the lock inode in place so concurrent starts cannot acquire a new file."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    try:
        descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600)
        file=os.fdopen(descriptor,"r+")
    except OSError:raise IntegrationBlocked("Private Telegram worker lock could not be opened") from None
    with file:
        info=os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise IntegrationBlocked("Unsafe Telegram worker lock")
        os.fchmod(file.fileno(),0o600)
        try:fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise IntegrationBlocked("A Telegram worker already holds this local lock") from None
        try:
            file.seek(0);file.truncate();file.write(str(os.getpid())+"\n");file.flush()
            yield
        finally:
            file.seek(0);file.truncate();file.flush()
            fcntl.flock(file.fileno(),fcntl.LOCK_UN)


@contextlib.contextmanager
def free_runtime():
    flags=("ALLOW_PAID_APIS","ALLOW_PUBLISHING")
    previous={key:os.environ.get(key) for key in flags}
    try:
        for key in flags:os.environ[key]="false"
        yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def safe_summary(result):
    """No callback payloads, chat/user IDs, update IDs, transcripts or exception text."""
    state="paused_kill_switch" if result.get("paused") else "stopped" if result.get("stopped") else "idle"
    counts={}
    for key in ("NEW","WAITING_VOICE","DONE","IGNORED","STALE","FAILED","NEEDS_RECONCILIATION"):
        value=result.get("counts",{}).get(key,0)
        if isinstance(value,int) and not isinstance(value,bool) and value>0:counts[key]=value
    updates=result.get("updates",[])
    if state=="idle" and isinstance(updates,list) and updates:state="processed"
    return {"state":state,"inbox_counts":counts,"voice_transcription":False,"paid_apis":False,"publication_actions":0}


def run_telegram_worker(engine,interval=10,once=False,*,worker=None,stop_event=None,emit=None,handle_signals=True):
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not math.isfinite(interval) or not 10<=interval<=3600:
        raise ValueError("Telegram poll interval must be 10–3600 seconds")
    if os.getenv("ALLOW_EXTERNAL_REQUESTS")!="true":raise IntegrationBlocked("Telegram polling requires explicit outbound authorization")
    for name in ("TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","TELEGRAM_USER_ID"):credential(name)
    stop_event=stop_event or threading.Event()
    emit=emit or (lambda record:print(json.dumps(record,sort_keys=True),flush=True))
    handlers={};cycles=errors=0;previous=None
    lock=Path(engine.db_path).resolve().with_name("telegram-worker.lock")
    with worker_lock(lock),free_runtime():
        worker=worker or TelegramWorker(engine)
        def stop(signum,frame):stop_event.set()
        try:
            if handle_signals:
                for signum in (signal.SIGINT,signal.SIGTERM):
                    handlers[signum]=signal.getsignal(signum);signal.signal(signum,stop)
            emit({"state":"starting","interval_seconds":interval,"voice_transcription":False,"paid_apis":False,"publication_actions":0})
            while not stop_event.is_set():
                cycles+=1
                try:
                    if engine.status()["kill_switch"]:result={"paused":True,"counts":{},"updates":[]}
                    else:result=worker.poll_once(voice_enabled=False,max_voice_cost=None,stop_requested=stop_event.is_set)
                    record=safe_summary(result)
                    # Offset is used only for local change detection, never emitted.
                    fingerprint=(json.dumps(record,sort_keys=True),result.get("offset"))
                except Exception:
                    errors+=1
                    record={"state":"error","reason":"poll_failed_details_suppressed","voice_transcription":False,"paid_apis":False,"publication_actions":0}
                    fingerprint=(json.dumps(record,sort_keys=True),None)
                if fingerprint!=previous:
                    emit(record);previous=fingerprint
                if once or stop_event.is_set():break
                stop_event.wait(interval)
        finally:
            for signum,handler in handlers.items():signal.signal(signum,handler)
    return {"state":"stopped","cycles":cycles,"errors":errors,"exit_reason":"once" if once else "stop_requested","exit_code":1 if once and errors else 0,"voice_transcription":False,"paid_apis":False,"publication_actions":0}
