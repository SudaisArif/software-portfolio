"""Context-preserving clip suggestions. Rankings are editorial heuristics, not virality."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


class ClipError(ValueError):
    pass


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def https_url(value):
    if not isinstance(value, str): return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def validate_transcript(transcript):
    if not isinstance(transcript, dict) or not https_url(transcript.get("source_url")):
        raise ClipError("Transcript requires an HTTPS source_url")
    if not re.fullmatch(r"[0-9a-f]{64}", transcript.get("source_sha256", "")):
        raise ClipError("Transcript must identify the exact source file SHA-256")
    if not isinstance(transcript.get("transcript_reviewed_by"), str) or not transcript["transcript_reviewed_by"].strip():
        raise ClipError("A human must verify the transcript against the source audio before clipping")
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 20000:
        raise ClipError("Transcript requires 1–20,000 timestamped segments")
    previous = 0.0
    normalized = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict): raise ClipError("Transcript segment must be an object")
        start, end, text = segment.get("start"), segment.get("end"), segment.get("text")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start,end)):
            raise ClipError("Transcript timestamps must be finite numbers")
        if not 0 <= start < end or start < previous:
            raise ClipError("Transcript segments must be ordered and nonoverlapping")
        if not isinstance(text,str) or not text.strip() or len(text)>2000:
            raise ClipError("Transcript text is missing or exceeds 2,000 characters")
        normalized.append({"index":index,"start":float(start),"end":float(end),"text":text.strip(),"speaker":str(segment.get("speaker", ""))})
        previous=end
    return normalized


def _caveat(text):
    return bool(re.match(r"\s*(but|however|although|except|unless|yet|that (doesn't|does not)|this (doesn't|does not)|not (everyone|always)|in contrast|the caveat|to be clear)\b", text, re.I))


def _continuation(text):
    return bool(re.match(r"\s*(and|so|because|which|therefore|that's why|that is why|it|they|this|that|these|those|but|however)\b", text, re.I))


def _sentence_end(text):
    return bool(re.search(r"[.!?][\"'”’)]*$",text.strip()))


def _context_bounds(segments,start,end,max_seconds):
    # Never begin halfway through a sentence, dangling answer, or obvious contrast.
    while start>0 and (_continuation(segments[start]["text"]) or _caveat(segments[start]["text"]) or not _sentence_end(segments[start-1]["text"])):
        start-=1
        if segments[end]["end"]-segments[start]["start"]>max_seconds:return None
    # Finish a sentence and preserve immediately following limitations/negations.
    while end+1<len(segments) and (not _sentence_end(segments[end]["text"]) or _caveat(segments[end+1]["text"])):
        end+=1
        if segments[end]["end"]-segments[start]["start"]>max_seconds:return None
    if segments[end]["end"]-segments[start]["start"]>max_seconds:
        return None
    return start,end


def _score(text,duration):
    lower=text.lower()
    evidence=sum(bool(re.search(r"\b"+word+r"\b",lower)) for word in ("study","evidence","research","experiment","measured"))
    contrast=sum(bool(re.search(r"\b"+word+r"\b",lower)) for word in ("but","however","instead","less","more"))
    concrete=bool(re.search(r"\d",text))
    question="?" in text
    usefulness=bool(re.search(r"\b(try|start|choose|compare|measure|track|practice)\b",lower))
    return min(100,35+min(evidence,2)*10+min(contrast,2)*8+concrete*8+question*7+usefulness*7+(5 if 25<=duration<=55 else 0))


def suggest_clips(transcript,min_seconds=20,max_seconds=90,limit=5):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (min_seconds,max_seconds)) or not 20<=min_seconds<=max_seconds<=90 or isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=30:
        raise ClipError("Choose 20–90 seconds and 1–30 candidates")
    segments=validate_transcript(transcript)
    fingerprint=digest_json(transcript)
    candidates={}
    for first in range(len(segments)):
        # Try the first qualifying endpoint and a somewhat longer one, bounded to avoid quadratic work.
        examined=0
        for last in range(first,min(len(segments),first+80)):
            duration=segments[last]["end"]-segments[first]["start"]
            if duration>max_seconds:break
            if duration<min_seconds:continue
            bounds=_context_bounds(segments,first,last,max_seconds)
            if bounds is None:continue
            start,end=bounds
            duration=segments[end]["end"]-segments[start]["start"]
            if duration<min_seconds:continue
            selected=segments[start:end+1]
            text=" ".join(s["text"] for s in selected)
            headlines=["A training claim worth a closer look"]
            if re.search(r"\b(study|research|experiment|measured)\b",text,re.I):headlines.insert(0,"What the study actually measured")
            if any(_caveat(s["text"]) for s in selected):headlines.insert(0,"The caveat changes the takeaway")
            if selected[0]["text"].endswith("?") and len(selected[0]["text"])<=55:headlines.insert(0,selected[0]["text"])
            key=f"{start}:{end}"
            candidate={"source_url":transcript["source_url"],"source_sha256":transcript["source_sha256"],
                       "transcript_sha256":fingerprint,"start":selected[0]["start"],"end":selected[-1]["end"],
                       "duration_seconds":duration,"first_segment":start,"last_segment":end,"text":text,
                       "hook_quote":selected[0]["text"],"headline":headlines[0],"headline_proposals":headlines,"headline_review_required":True,
                       "editorial_score":_score(text,duration),"score_type":"heuristic_editorial_not_measured_virality",
                       "virality_verified":False,"human_context_review_required":True,
                       "context_before":" ".join(s["text"] for s in segments[max(0,start-2):start]),
                       "context_after":" ".join(s["text"] for s in segments[end+1:end+3]),
                       "context_flags":["Contains a limitation; keep it intact"] if any(_caveat(s["text"]) for s in selected) else [],
                       "human_approved":False,"publishable":False}
            candidate["candidate_id"]=digest_json({k:candidate[k] for k in ("source_sha256","transcript_sha256","start","end")})[:24]
            candidates[key]=candidate
            examined+=1
            if examined>=3:break
    ranked=sorted(candidates.values(),key=lambda c:(-c["editorial_score"],abs(c["duration_seconds"]-40),c["start"]))
    chosen=[]
    for candidate in ranked:
        if any(candidate["start"]<old["end"] and candidate["end"]>old["start"] for old in chosen):continue
        chosen.append(candidate)
        if len(chosen)==limit:break
    return {"source_url":transcript["source_url"],"candidate_count":len(chosen),"candidates":chosen,
            "scope":"Sentence-boundary and immediate-caveat heuristics only. A human must review full context, factual claims and transcript accuracy. No candidate is claimed viral.",
            "source_metrics":transcript.get("source_metrics"),"source_metrics_scope":"User-supplied evidence; not independently verified by this command"}


def validate_candidate(transcript,candidate):
    segments=validate_transcript(transcript)
    if not isinstance(candidate,dict):raise ClipError("Candidate must be an object")
    if candidate.get("transcript_sha256")!=digest_json(transcript) or candidate.get("source_sha256")!=transcript["source_sha256"] or candidate.get("source_url")!=transcript["source_url"]:
        raise ClipError("Candidate is bound to a different or changed transcript/source")
    start,end=candidate.get("first_segment"),candidate.get("last_segment")
    if any(isinstance(v,bool) or not isinstance(v,int) for v in (start,end)) or not 0<=start<=end<len(segments):
        raise ClipError("Invalid candidate segment range")
    selected=segments[start:end+1]
    if candidate.get("start")!=selected[0]["start"] or candidate.get("end")!=selected[-1]["end"] or candidate.get("text")!=" ".join(s["text"] for s in selected):
        raise ClipError("Clip timing or transcript text was altered; generate a new candidate")
    if candidate.get("hook_quote")!=selected[0]["text"]:raise ClipError("Extractive hook must remain an exact source quote")
    if not 20<=candidate["end"]-candidate["start"]<=90:
        raise ClipError("Clip must be 20–90 seconds")
    bounds=_context_bounds(segments,start,end,90)
    if bounds!=(start,end):
        raise ClipError("Clip omits sentence context or an immediate qualification")
    expected_id=digest_json({k:candidate[k] for k in ("source_sha256","transcript_sha256","start","end")})[:24]
    if candidate.get("candidate_id")!=expected_id:raise ClipError("Candidate identifier does not match its boundaries")
    return selected


def validate_rights(rights,transcript):
    if not isinstance(rights,dict) or rights.get("rights_status") not in {"original","licensed","public_domain"}:
        raise ClipError("Source rights are unknown or unsuitable for reuse")
    if rights.get("source_url")!=transcript["source_url"] or rights.get("source_sha256")!=transcript["source_sha256"]:
        raise ClipError("Rights evidence is not bound to this exact source file")
    for key in ("commercial_use_allowed","adaptation_allowed","source_audio_included","third_party_elements_reviewed"):
        if rights.get(key) is not True:raise ClipError("Rights record must explicitly permit "+key)
    for key in ("rights_holder","attribution","reviewed_by","owner_attestation"):
        if not isinstance(rights.get(key),str) or not rights[key].strip():raise ClipError("Rights record requires "+key)
    if len(rights["attribution"])>100:raise ClipError("Use a concise attribution under 100 characters; full license remains in the manifest")
    if rights["rights_status"]!="original" and not https_url(rights.get("license_url")):
        raise ClipError("An HTTPS permission/license evidence URL is required")
    return rights


def import_review(engine,transcript,candidate,rights):
    """Create a draft only. No ownership/rights check is a release authorization."""
    validate_candidate(transcript,candidate)
    validate_rights(rights,transcript)
    concept="licensed-clip:"+candidate["candidate_id"]
    existing=[j for j in engine.list_jobs() if j["concept"]==concept or any(s.get("source_sha256")==transcript["source_sha256"] and s.get("interval")==[candidate["start"],candidate["end"]] for s in j.get("sources",[]) if isinstance(s,dict))]
    if existing:return existing[0]
    job=engine.create_job(candidate.get("headline") or "Source clip for review",concept)
    source={"url":transcript["source_url"],"source_sha256":transcript["source_sha256"],"interval":[candidate["start"],candidate["end"]]}
    engine.set_research(job["id"],[source],json.dumps({"candidate":candidate,"rights":rights,"scope":"A source excerpt is not scientific claim verification. Review full context and claims before approval."},ensure_ascii=False))
    return engine.set_script(job["id"],candidate["text"])
