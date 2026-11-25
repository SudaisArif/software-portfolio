import argparse
import json
from pathlib import Path
import sys
from .core import ClipError,suggest_clips,import_review
from .render import render_clip
from .youtube import YouTubeMetadata


def read(path):
    path=Path(path)
    if path.stat().st_size>10_000_000:raise ClipError("JSON input exceeds 10 MB")
    return json.loads(path.read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(description="REP SIGNAL permission-aware clipping; no public-video downloader or publishing")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("suggest");p.add_argument("transcript");p.add_argument("--out",required=True);p.add_argument("--limit",type=int,default=5);p.add_argument("--min-seconds",type=float,default=20);p.add_argument("--max-seconds",type=float,default=90)
    p=sub.add_parser("render");p.add_argument("source");p.add_argument("transcript");p.add_argument("candidates");p.add_argument("rights");p.add_argument("--index",type=int,default=0);p.add_argument("--output",required=True);p.add_argument("--layout",choices=["contain","crop"],default="contain");p.add_argument("--focus-x",type=float,default=.5);p.add_argument("--context-reviewed-by",default="")
    p=sub.add_parser("import-review");p.add_argument("transcript");p.add_argument("candidates");p.add_argument("rights");p.add_argument("--index",type=int,default=0);p.add_argument("--db",default="data/media.db")
    p=sub.add_parser("discover");p.add_argument("query");p.add_argument("--out",required=True);p.add_argument("--limit",type=int,default=10);p.add_argument("--include-standard-license",action="store_true");p.add_argument("--live",action="store_true",required=True)
    args=parser.parse_args(argv)
    if args.command=="suggest":result=suggest_clips(read(args.transcript),args.min_seconds,args.max_seconds,args.limit)
    elif args.command=="discover":result=YouTubeMetadata().discover(args.query,args.limit,not args.include_standard_license)
    else:
        candidates=read(args.candidates)["candidates"]
        if not 0<=args.index<len(candidates):raise ClipError("Candidate index is out of bounds")
        transcript,rights=read(args.transcript),read(args.rights)
        if args.command=="render":result=render_clip(args.source,transcript,candidates[args.index],rights,args.output,args.focus_x,args.layout,args.context_reviewed_by)
        else:
            from media_engine import Engine
            result=import_review(Engine(args.db),transcript,candidates[args.index],rights)
    if args.command in {"suggest","discover"}:
        out=Path(args.out)
        if out.exists():raise ClipError("Output already exists; choose a new filename")
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
        print(json.dumps({"saved":str(out),"candidates":len(result["candidates"])}))
    else:print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=="__main__":
    try:main()
    except (ClipError,ValueError,KeyError,IndexError,FileNotFoundError,RuntimeError) as exc:
        print("Blocked: "+str(exc),file=sys.stderr);raise SystemExit(1)
