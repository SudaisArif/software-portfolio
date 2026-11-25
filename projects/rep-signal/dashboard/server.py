"""Loopback-only review UI. Token authentication, Origin/Host checks, CSP and bounded bodies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
import hmac
import json
import math
import mimetypes
import os
import re
from pathlib import Path
import secrets
import urllib.parse
from media_engine import Engine, GateError
from media_engine.engine import file_hash
from pipeline import ROOT, editorial_check


PREVIEWS = (
    {"id":"original_feed", "stem":"review-2026-11-18/original-study-feed-v3", "title":"Is your rest timer costing you strength?", "lane":"Revised original", "audio_label":"Licensed synthetic narration · real training footage · original sound design", "review_label":"LOCAL REVIEW · RELEASE NOT APPROVED", "optional":True},
    {"id":"original_narrated", "stem":"review-2026-11-17/original-study", "title":"Rest longer. Get stronger?", "lane":"Archived original study", "audio_label":"Licensed synthetic narration · real training footage · original sound design", "review_label":"LOCAL REVIEW · RELEASE NOT APPROVED", "optional":True},
    {"id":"clip_progress", "stem":"review-2026-11-17/clip-progress-proof-v2", "title":"Stronger—or just sweatier?", "lane":"New contextual source clip", "audio_label":"Original human source voice · factual editorial excerpt", "review_label":"LOCAL REVIEW · RELEASE NOT APPROVED", "optional":True},
    {"id":"study", "stem":"study-sample", "title":"Rest more. Gain more?", "lane":"Study video", "audio_label":"Intentionally voice-free · original sound design", "review_label":"LOCAL REVIEW · RELEASE NOT APPROVED"},
    {"id":"study_recovery", "stem":"study-recovery", "title":"Recovery, under review", "lane":"Second study video", "audio_label":"Intentionally voice-free · original sound design", "review_label":"LOCAL REVIEW · RELEASE NOT APPROVED"},
    {"id":"human", "stem":"human-clip-preview", "title":"A real voice, in context", "lane":"Natural source voice", "audio_label":"Original human source voice · educational preview", "review_label":"COMMERCIAL RIGHTS NOT CLEARED"},
    {"id":"original", "stem":"sample", "title":"The next rep", "lane":"Archived original", "audio_label":"Archived animation · synthetic narration", "review_label":"ARCHIVED TEST · RELEASE NOT APPROVED"},
)
SERVICE_DEFAULTS = (
    {"id":"brand_email","title":"Brand Google account","status":"verified","detail":"Dedicated brand mailbox verified. Account details stay in the private setup register."},
    {"id":"github","title":"Private source repository","status":"created_private","detail":"Private repository created. Code push pending.","url":"https://github.com/SudaisArif/rep-signal"},
    {"id":"youtube","title":"YouTube","status":"pending","detail":"Dedicated channel setup and credentials pending."},
    {"id":"instagram","title":"Instagram","status":"pending","detail":"Account setup, terms and credentials pending."},
    {"id":"tiktok","title":"TikTok","status":"pending","detail":"Account setup, terms and credentials pending."},
    {"id":"buffer","title":"Publishing connection","status":"pending","detail":"Provider account and platform consent pending. Publication remains disabled."},
    {"id":"voice","title":"Natural narration","status":"pending","detail":"Authentic source audio and human recording are available directions. Paid voice credentials and billing remain pending."},
    {"id":"writing","title":"Paid writing API","status":"pending","detail":"Adapter prepared. Paid API work is not authorized."},
    {"id":"telegram","title":"Private review notifications","status":"pending","detail":"Local review works now. Telegram credentials and account setup remain pending."},
    {"id":"n8n","title":"Workflow automation","status":"pending","detail":"Local setup in progress. No live automation is confirmed."},
    {"id":"database","title":"Database","status":"pending","detail":"Read the local setup register for the latest database state."},
    {"id":"storage","title":"Media storage","status":"pending","detail":"Read the local setup register for the latest storage state."},
    {"id":"analytics","title":"Analytics and monitoring","status":"pending","detail":"No channel performance is available yet."},
)


def fixed_file(root, relative):
    """Only literal, project-owned files; symlinks cannot turn this into a file server."""
    try:
        root=Path(root).resolve();target=root/relative
        return target if target.resolve()==target and target.is_file() else None
    except (OSError,RuntimeError):return None


def read_public_json(root,relative):
    path=fixed_file(root,relative)
    if not path or path.stat().st_size>2_000_000:return {}
    try:
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (ValueError,OSError):return {}


def public_text(value,limit=500):
    return value[:limit] if isinstance(value,str) else ""


def public_url(value):
    if not isinstance(value,str) or len(value)>2000:return None
    try:
        parsed=urllib.parse.urlsplit(value)
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:return None
        # Keep only YouTube's public video ID query; strip incidental tokens/tracking.
        query=""
        if parsed.hostname in {"www.youtube.com","youtube.com"}:
            video=urllib.parse.parse_qs(parsed.query).get("v",[""])[0]
            if len(video)==11 and all(c.isalnum() or c in "_-" for c in video):query=urllib.parse.urlencode({"v":video})
        return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,query,""))
    except ValueError:return None


def preview_catalog(root):
    previews=[]
    for spec in PREVIEWS:
        stem=spec["stem"];raw=read_public_json(root,f"output/{stem}.json")
        if spec.get("optional") and not (raw and fixed_file(root,f"output/{stem}.mp4")):continue
        item={k:v for k,v in spec.items() if k not in {"stem","optional"}}
        item.update(title=public_text(raw.get("title"),160) or spec["title"],available=bool(raw and fixed_file(root,f"output/{stem}.mp4")),video_url=f"/{stem}.mp4",poster_url=f"/{stem}.jpg",script=public_text(raw.get("script"),20000),script_kind=public_text(raw.get("script_kind"),100),factual_caveat=public_text(raw.get("factual_caveat"),4000),human_recording_script=public_text(raw.get("human_recording_script"),10000),human_approved=False,publishable=False)
        duration=raw.get("duration_seconds")
        item["duration_seconds"]=duration if isinstance(duration,(int,float)) and not isinstance(duration,bool) and math.isfinite(duration) and 0<duration<3600 else None
        dimensions=raw.get("dimensions")
        item["dimensions"]=dimensions if isinstance(dimensions,list) and len(dimensions)==2 and all(isinstance(v,int) and not isinstance(v,bool) and 0<v<=16000 for v in dimensions) else [1080,1920]
        sources=[]
        for source in raw.get("sources",[])[:20] if isinstance(raw.get("sources"),list) else []:
            if not isinstance(source,dict):continue
            url=public_url(source.get("url"))
            if not url:continue
            sources.append({"url":url,"title":public_text(source.get("title"),300) or "Source","scope":public_text(source.get("scope") or source.get("claim_scope"),3000),"design":public_text(source.get("design"),1000)})
        source_url=public_url(raw.get("source_url"))
        if source_url and not any(source["url"]==source_url for source in sources):sources.append({"url":source_url,"title":"Original source","scope":"","design":""})
        item["sources"]=sources
        interval=raw.get("source_interval")
        if isinstance(interval,dict) and all(isinstance(interval.get(k),(int,float)) and not isinstance(interval[k],bool) and math.isfinite(interval[k]) for k in ("start","end")) and 0<=interval["start"]<interval["end"]:
            item["source_interval"]={k:interval[k] for k in ("start","end")}
        previews.append(item)
    default=next((p["id"] for p in previews if p["available"]),"study")
    return {"previews":previews,"default_preview_id":default}


def public_services(root):
    raw=read_public_json(root,"config/service-status.json")
    configured={s["id"]:s for s in raw.get("services",[]) if isinstance(s,dict) and isinstance(s.get("id"),str)} if isinstance(raw.get("services"),list) else {}
    services=[]
    for default in SERVICE_DEFAULTS:
        item=dict(default);source=configured.get(item["id"],{})
        for key,limit in (("title",100),("detail",1000)):
            if public_text(source.get(key),limit):item[key]=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[private account]",public_text(source[key],limit))
        if source.get("status") in {"pending","verified","created_private","configured","blocked","owner_step","installing","local_ready"}:item["status"]=source["status"]
        if public_url(source.get("url")):item["url"]=public_url(source["url"])
        services.append(item)
    # Authorization and these initial verified milestones were explicitly provided by the owner on Nov 15.
    date=raw.get("setup_authorized_at")
    return {"services":services,"setup_authorized_at":date if isinstance(date,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",date) else "2026-11-15"}


def review_token(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    os.chmod(path, 0o600)
    return path.read_text().strip()


def make_server(engine, port=8766, token=None, root=None):
    root=Path(root) if root is not None else ROOT
    token = token or os.getenv("REVIEW_TOKEN") or review_token(ROOT / "data/review-token")

    media_session=secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TrainingStudio"
        def log_message(self, fmt, *args):
            # No URLs, bodies, scripts, feedback, tokens, or third-party response bodies in logs.
            pass

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def authorized(self):
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def authorized_media(self):
            try:
                cookies=SimpleCookie();cookies.load(self.headers.get("Cookie",""))
                item=cookies.get("rep_signal_review")
                return bool(item) and hmac.compare_digest(item.value,media_session)
            except (CookieError,ValueError):return False

        def send(self, status, data, content_type="application/json", headers=None):
            body = json.dumps(data, allow_nan=False).encode() if content_type == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key,value in (headers or {}).items():self.send_header(key,value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error":"Invalid host"})
            path = urllib.parse.urlsplit(self.path).path
            if path == "/health":
                return self.send(200, {"ok": True, "mode": "local", "external_requests": False})
            if path == "/api/preview":
                s=engine.status()
                return self.send(200,{**preview_catalog(root),**public_services(root),"status":{"kill_switch":s["kill_switch"],"publication_enabled":s["publication_enabled"],"counts":s["counts"],"costs":{k:s["costs"].get(k,0) for k in ("approved_usd","spent_usd","reserved_usd")}}})
            media_match=re.fullmatch(r"/api/previews/([0-9a-f]{32})/video",path)
            if path.startswith("/api/") and not self.authorized() and not (media_match and self.authorized_media()):
                return self.send(401, {"error":"Unlock to read saved jobs, feedback and activity"})
            if path == "/api/state":
                data = {"jobs":engine.list_jobs(), "status":engine.status(), "events":engine.audit_log(),
                        **preview_catalog(root),**public_services(root),
                        "metrics":engine.metrics_report()}
                return self.send(200, data)
            if path.startswith("/api/jobs/"):
                try:
                    return self.send(200, engine.get_job(path.rsplit("/",1)[1]))
                except KeyError:
                    return self.send(404, {"error":"Job not found"})
            files = {"/":"dashboard/index.html", "/app.js":"dashboard/app.js", "/style.css":"dashboard/style.css"}
            for spec in PREVIEWS:
                files[f"/{spec['stem']}.mp4"]=f"output/{spec['stem']}.mp4"
                files[f"/{spec['stem']}.jpg"]=f"output/{spec['stem']}.poster.jpg"
            target = fixed_file(root,files[path]) if path in files else None
            if media_match:
                try:
                    preview=engine.get_preview(media_match[1]);engine._verify_preview(preview,engine.get_job(preview["job_id"]))
                    candidate=Path(preview["path"])
                    base=Path(engine.db_path).resolve().parent/"review-artifacts"
                    if candidate.is_symlink() or not candidate.resolve().is_relative_to(base):raise GateError("Unsafe preview location")
                    target=candidate
                except KeyError:return self.send(404,{"error":"Preview not found"})
                except (GateError,OSError):return self.send(409,{"error":"Preview no longer matches the current script revision or stored files"})
            if not target:
                return self.send(404, {"error":"Not found"})
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            # Serve byte ranges for browser video playback, including Safari.
            if content_type == "video/mp4":
                size = target.stat().st_size
                start, end = 0, size-1
                range_header = self.headers.get("Range")
                if range_header:
                    try:
                        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                        if not match or not any(match.groups()): raise ValueError()
                        if match[1]:
                            start = int(match[1]); end = min(int(match[2]),size-1) if match[2] else size-1
                        else:
                            length=int(match[2])
                            if length<=0: raise ValueError()
                            start=max(0,size-length); end=size-1
                        if not 0 <= start <= end < size: raise ValueError()
                    except ValueError:
                        return self.send(416, {"error":"Invalid range"})
                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end-start+1))
                self.send_header("Cache-Control", "no-store")
                if range_header: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                with target.open("rb") as f:
                    f.seek(start); remaining=end-start+1
                    while remaining:
                        chunk=f.read(min(65536,remaining))
                        if not chunk: break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            # Switching videos or seeking can cancel an active range request.
                            return
                        remaining-=len(chunk)
                return
            self.send(200, target.read_bytes(), content_type)

        def do_POST(self):
            if not self.valid_host():
                return self.send(403, {"error":"Invalid host"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://localhost:{self.server.server_port}", f"http://127.0.0.1:{self.server.server_port}"}:
                return self.send(403, {"error":"Cross-origin request rejected"})
            if not self.authorized():
                return self.send(401, {"error":"Unlock review controls with the local access key"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error":"JSON required"})
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 100000: raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(size))
                path = urllib.parse.urlsplit(self.path).path
                if path == "/api/unlock": result = {"unlocked":True}
                elif path == "/api/review":
                    result=engine.review_script(body["id"],body["decision"],actor="dashboard-owner",revision=body["revision"],feedback=body.get("feedback",""))
                elif path == "/api/revise":
                    current=engine.get_job(body["id"])
                    if current["revision"] != body["revision"]: raise ValueError("Script changed; refresh before editing")
                    screen=editorial_check(body["script"],current["sources"])
                    if not screen["passed"]: raise ValueError("; ".join(screen["problems"]))
                    result=engine.set_script(body["id"],body["script"],expected_revision=body["revision"])
                elif path == "/api/preview-qc":
                    preview=engine.get_preview(body["preview_id"])
                    if preview["job_id"]!=body["id"] or preview["revision"]!=body["revision"]:raise ValueError("Preview does not belong to the selected job revision")
                    result=engine.run_preview_qc(preview["id"])
                elif path == "/api/stage-preview":
                    preview=engine.get_preview(body["preview_id"])
                    if preview["job_id"]!=body["id"]:raise ValueError("Preview does not belong to the selected job")
                    result=engine.stage_preview(preview["id"],revision=body["revision"],artifact_sha256=body["artifact_sha256"])
                elif path == "/api/approve-release":
                    result=engine.approve_release(body["id"],actor="dashboard-owner",artifact_sha256=body["artifact_sha256"],revision=body["revision"])
                elif path == "/api/kill":
                    if not isinstance(body.get("enabled"),bool): raise ValueError("enabled must be boolean")
                    engine.kill_switch(body["enabled"],actor="dashboard-owner"); result=engine.status()
                elif path == "/api/worker":
                    result={"recovered":engine.recover_expired_leases(),"dry_run":engine.publish_due({},dry_run=True)}
                else: return self.send(404,{"error":"Not found"})
                self.send(200,result,headers={"Set-Cookie":"rep_signal_review="+media_session+"; HttpOnly; SameSite=Strict; Path=/api/previews/"} if path=="/api/unlock" else None)
            except (ValueError,KeyError,TypeError) as exc:
                self.send(400,{"error":str(exc)[:300]})
            except Exception:
                self.send(500,{"error":"Operation failed; inspect local state before retrying"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(engine, port=8766):
    server = make_server(engine,port)
    print(f"Training Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print("Read-only preview is open. Unlock decisions using the local data/review-token file; never paste it in chat.",flush=True)
    server.serve_forever()
