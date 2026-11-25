#!/usr/bin/env python3
"""Training Studio CLI. All commands are offline unless explicitly named and enabled."""
import argparse
import json
from pathlib import Path
import os
import sys
from media_engine import Engine
from pipeline import ROOT, seed_sample, generate


def output(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(ROOT/"data/media.db"))
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("init",help="Initialize local database and an unapproved sample script")
    sub.add_parser("status")
    s=sub.add_parser("serve");s.add_argument("--port",type=int,default=8766)
    sub.add_parser("dry-run",help="Evaluate schedule gates without sending any request")
    sub.add_parser("worker",help="Recover expired leases and evaluate local schedule without publishing")
    s=sub.add_parser("stop");s.add_argument("--resume",action="store_true")
    s=sub.add_parser("review");s.add_argument("job_id");s.add_argument("decision",choices=["approve","reject","revise"]);s.add_argument("--revision",type=int,required=True);s.add_argument("--feedback",default="");s.add_argument("--actor",default="owner-cli")
    s=sub.add_parser("generate");s.add_argument("brief",type=Path);s.add_argument("--max-cost-per-call",type=float,required=True);s.add_argument("--live",action="store_true",required=True)
    s=sub.add_parser("authorize-budget",help="Record the owner's explicitly granted monthly budget; never a substitute for actual consent");s.add_argument("amount",type=float)
    s=sub.add_parser("narrate");s.add_argument("job_id");s.add_argument("--max-cost",type=float,required=True);s.add_argument("--live",action="store_true",required=True)
    s=sub.add_parser("transcribe");s.add_argument("audio",type=Path);s.add_argument("--max-cost",type=float,required=True);s.add_argument("--live",action="store_true",required=True)
    s=sub.add_parser("notify-review");s.add_argument("job_id");s.add_argument("--live",action="store_true",required=True)
    s=sub.add_parser("telegram-poll");s.add_argument("--live",action="store_true",required=True);s.add_argument("--voice-enabled",action="store_true");s.add_argument("--max-voice-cost",type=float)
    s=sub.add_parser("telegram-worker",help="Local owner review polling; voice, paid APIs and publication disabled");s.add_argument("--live",action="store_true",required=True);s.add_argument("--interval",type=float,default=10);s.add_argument("--once",action="store_true")
    s=sub.add_parser("render-approved");s.add_argument("job_id");s.add_argument("brief",type=Path);s.add_argument("narration",type=Path);s.add_argument("alignment",type=Path);s.add_argument("--voice-license-url",required=True);s.add_argument("--license-attestation-file",type=Path,required=True);s.add_argument("--style",choices=["cinematic","editorial","storytelling"],default="cinematic")
    s=sub.add_parser("import-review-artifact",help="Snapshot a local rendered video into unapproved review; never approves or publishes");s.add_argument("video",type=Path);s.add_argument("--manifest",type=Path);s.add_argument("--job-id");s.add_argument("--revision",type=int)
    s=sub.add_parser("preview-qc",help="Measure an imported preview without approving its script");s.add_argument("preview_id")
    s=sub.add_parser("stage-preview",help="Bind an exact preview to final QC after owner script approval; no release approval");s.add_argument("preview_id");s.add_argument("--revision",type=int,required=True);s.add_argument("--artifact-sha256",required=True)
    s=sub.add_parser("supabase-backup",help="Plan private backup offline; --live requires separately authorized credentials/uploads");s.add_argument("preview_id");s.add_argument("--live",action="store_true");s.add_argument("--verify-existing",action="store_true")
    s=sub.add_parser("qc");s.add_argument("job_id")
    s=sub.add_parser("approve-release");s.add_argument("job_id");s.add_argument("--artifact-sha256",required=True);s.add_argument("--revision",type=int);s.add_argument("--actor",default="owner-cli")
    s=sub.add_parser("schedule");s.add_argument("job_id");s.add_argument("--at",required=True);s.add_argument("--platforms",nargs="+",choices=["youtube","instagram","tiktok"],required=True)
    for command,help_text in (("manual-schedule","Record exact owner-chat consent and daily quota; no provider request"),("manual-begin","Claim one authorized UI submission before sending; never retries"),("manual-record","Record observed Buffer receipt or verified public URL; never sends")):
        s=sub.add_parser(command,help=help_text);s.add_argument("request",type=Path,help="JSON object containing the explicit method arguments")
    s=sub.add_parser("import-metrics");s.add_argument("path",type=Path)
    args=p.parse_args(argv);engine=Engine(args.db)
    if args.command=="init":
        job=seed_sample(engine);output({"database":args.db,"job_id":job["id"],"state":job["state"],"approved":False})
    elif args.command=="status":output(engine.status())
    elif args.command=="serve":
        seed_sample(engine)
        from dashboard.server import serve
        serve(engine,args.port)
    elif args.command=="dry-run":output(engine.publish_due({},dry_run=True))
    elif args.command=="worker":
        output({"recovered":engine.recover_expired_leases(),"schedule":engine.publish_due({},dry_run=True),"external_actions":0})
    elif args.command=="stop":
        engine.kill_switch(not args.resume,actor="owner-cli");output(engine.status())
    elif args.command=="review":output(engine.review_script(args.job_id,args.decision,actor=args.actor,revision=args.revision,feedback=args.feedback))
    elif args.command=="authorize-budget":
        engine.approve_budget(args.amount,actor="owner-cli");output(engine.status())
    elif args.command=="generate":
        result=generate(engine,json.loads(args.brief.read_text()),args.max_cost_per_call)
        target=ROOT/"data/last-generation.json";target.write_text(json.dumps(result,indent=2));os.chmod(target,0o600)
        output({"accepted":result["accepted"],"result_file":str(target),"state":result.get("job",{}).get("state")})
    elif args.command=="narrate":
        from integrations.elevenlabs import ElevenLabs
        job=engine.get_job(args.job_id)
        if job["state"]!="APPROVED" or job["approved_revision"]!=job["revision"]:
            raise ValueError("Approve this script revision before generating production narration")
        reservation=engine.reserve_cost("elevenlabs",args.max_cost)
        audio,alignment=ElevenLabs().synthesize(job["script"])
        folder=ROOT/"data/narration"/job["id"]/str(job["revision"]);folder.mkdir(parents=True,exist_ok=True)
        (folder/"voice.mp3").write_bytes(audio);(folder/"alignment.json").write_text(json.dumps(alignment))
        (folder/"provenance.json").write_text(json.dumps({"provider":"ElevenLabs","revision":job["revision"],"rights_status":"unknown_until_plan_and_voice_license_verified","cost_reservation_id":reservation}))
        output({"folder":str(folder),"cost_reservation_id":reservation,"note":"Cost remains reserved pending verified usage reconciliation; register voice license evidence before release."})
    elif args.command=="transcribe":
        from integrations.openai_api import OpenAI
        reservation=engine.reserve_cost("openai:transcription",args.max_cost)
        result=OpenAI().transcribe(args.audio);target=ROOT/"data/voice-feedback.json"
        target.write_text(json.dumps({"text":result["text"],"cost_reservation_id":reservation,"is_approval":False},indent=2));os.chmod(target,0o600)
        output({"transcript_file":str(target),"note":"Review transcript accuracy and attach as revision feedback; transcription never approves a job."})
    elif args.command=="notify-review":
        from integrations.telegram_worker import TelegramWorker
        output(TelegramWorker(engine).notify_review(args.job_id))
    elif args.command=="telegram-poll":
        from integrations.telegram_worker import TelegramWorker
        output(TelegramWorker(engine).poll_once(voice_enabled=args.voice_enabled,max_voice_cost=args.max_voice_cost))
    elif args.command=="telegram-worker":
        from integrations.telegram_service import run_telegram_worker
        result=run_telegram_worker(engine,interval=args.interval,once=args.once)
        output(result)
        if result["exit_code"]:raise SystemExit(result["exit_code"])
    elif args.command=="render-approved":
        from production import render_approved
        result=render_approved(engine,args.job_id,args.brief,args.narration,args.alignment,args.voice_license_url,
                               args.style,license_attestation=args.license_attestation_file.read_text())
        output({"output":result["output"],"qc":result["qc"],"awaiting_release_review":result["awaiting_release_review"]})
    elif args.command=="import-review-artifact":
        from preview_intake import import_review_artifact
        result=import_review_artifact(engine,args.video,args.manifest,job_id=args.job_id,expected_revision=args.revision)
        output({"job_id":result["job"]["id"],"revision":result["job"]["revision"],"state":result["job"]["state"],"preview_id":result["preview"]["id"],"artifact_sha256":result["preview"]["artifact_sha256"],"qc":result["qc"],"approval_created":False,"publishable":False})
    elif args.command=="preview-qc":output(engine.run_preview_qc(args.preview_id))
    elif args.command=="stage-preview":
        result=engine.stage_preview(args.preview_id,revision=args.revision,artifact_sha256=args.artifact_sha256)
        output({"job_id":result["job"]["id"],"state":result["job"]["state"],"qc":result["qc"],"awaiting_release_review":True,"publishable":False})
    elif args.command=="supabase-backup":
        from integrations.supabase_storage import SupabaseStorage,local_plan
        from integrations.keychain import write_private_json
        preview=engine.get_preview(args.preview_id)
        engine._verify_preview(preview,engine.get_job(preview["job_id"]))
        if engine.status()["kill_switch"]:raise ValueError("Emergency kill switch is on")
        plan=local_plan(preview["path"],preview["artifact_sha256"])
        if not args.live:
            output({**plan,"mode":"OFFLINE_PLAN","credential_names":["SUPABASE_URL","SUPABASE_STORAGE_KEY"],"required_flags":["ALLOW_EXTERNAL_REQUESTS=true","ALLOW_STORAGE_UPLOADS=true for an upload"],"no_network_request":True})
        else:
            adapter=SupabaseStorage()
            record=adapter.verify_existing(plan) if args.verify_existing else adapter.upload_verified(preview["path"],preview["artifact_sha256"])
            target=Path(engine.db_path).resolve().parent/("supabase-backup-"+preview["id"]+".json")
            write_private_json(target,record)
            output({"receipt_file":str(target),"storage_verified":record["storage_verified"],"sha256":record["sha256"],"public":False,"distribution_authorized":False})
    elif args.command=="qc":output(engine.run_qc(args.job_id))
    elif args.command=="approve-release":output(engine.approve_release(args.job_id,actor=args.actor,artifact_sha256=args.artifact_sha256,revision=args.revision))
    elif args.command=="schedule":output(engine.schedule(args.job_id,args.at,args.platforms))
    elif args.command in {"manual-schedule","manual-begin","manual-record"}:
        method={"manual-schedule":engine.schedule_manual,"manual-begin":engine.begin_manual_delivery,"manual-record":engine.record_manual_delivery}[args.command]
        output(method(**json.loads(args.request.read_text())))
    elif args.command=="import-metrics":
        records=json.loads(args.path.read_text())
        for r in records:engine.record_metrics(r["job_id"],r["platform"],r["values"],r["source"],r.get("observed_at"))
        output({"imported":len(records)})


if __name__=="__main__":
    try: main()
    except (ValueError,RuntimeError,KeyError) as exc:
        print("Blocked: "+str(exc),file=sys.stderr);raise SystemExit(1)
