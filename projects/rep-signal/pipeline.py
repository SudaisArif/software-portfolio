"""Content orchestration: offline fixture or separately authorized, budgeted generation."""
import difflib
import json
from pathlib import Path
import re
from integrations.openai_api import OpenAI
from integrations.http import IntegrationBlocked

ROOT = Path(__file__).resolve().parent


def editorial_check(script, sources, previous=()):
    guide = json.loads((ROOT / "config/voice-guide.json").read_text())
    problems = []
    words = re.findall(r"\b[\w'-]+\b", script)
    if not 35 <= len(words) <= 210:
        problems.append("Script should contain 35–210 words for a 20–90 second treatment; measured audio is authoritative.")
    for phrase in guide["ban_phrases"]:
        if phrase.casefold() in script.casefold():
            problems.append("Generic language: " + phrase)
    if not sources or any(not s.get("url", "").startswith("https://") for s in sources):
        problems.append("Missing source evidence")
    for older in previous:
        if difflib.SequenceMatcher(None, script.casefold(), older.casefold()).ratio() > .78:
            problems.append("Excessive similarity to a previous script")
            break
    return {"passed": not problems, "problems": problems,
            "word_count": len(words), "estimated_seconds": round(len(words)/135*60, 1),
            "scope": "Automated heuristic screen only; human evidence and originality review required"}


def seed_sample(engine):
    brief = json.loads((ROOT / "config/sample-brief.json").read_text())
    existing = [j for j in engine.list_jobs() if j["concept"] == "local-first-sample"]
    if existing:
        return existing[0]
    sources = brief.get("sources") or [{"url": u, "retrieved_at": "2026-11-13", "use": "creative brief"} for u in brief["source_urls"]]
    job = engine.create_job(brief["title"], "local-first-sample", sources=sources)
    engine.set_research(job["id"], sources, brief["evidence_boundary"])
    return engine.set_script(job["id"], brief["original_script"])


RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"title": {"type":"string"}, "script": {"type":"string"},
                   "reasoning": {"type":"string"}, "decision": {"type":"string", "enum":["accept","revise","reject"]},
                   "source_urls": {"type":"array", "items":{"type":"string"}},
                   "uncertainties": {"type":"array", "items":{"type":"string"}}},
    "required": ["title", "script", "reasoning", "decision", "source_urls", "uncertainties"]}


def generate(engine, brief, max_cost_per_call, api=None):
    """Five sequential creative stages; only records HUMAN_REVIEW, never approval.

    Reserve a conservatively approved upper bound before each request. Keep it
    reserved until a verified usage invoice can settle the actual amount.
    """
    api = api or OpenAI()
    if not brief.get("sources") or not brief.get("evidence"):
        raise ValueError("Supply reviewed source records AND evidence excerpts; the model must not invent research")
    if len(json.dumps(brief).encode()) > 12000:
        raise ValueError("Brief exceeds the 12 KB input limit; supply a focused evidence packet")
    if not isinstance(max_cost_per_call, (int, float)) or not .1 <= max_cost_per_call <= 5:
        raise ValueError("Reserve $0.10–$5 per call; the reviewed model/request bounds require at least $0.10")
    allowed_urls = {s["url"] for s in brief["sources"]}
    roles = json.loads((ROOT / "config/agents.json").read_text())["agents"][:5]
    history = []
    data = dict(brief)
    for role in roles:
        if len(json.dumps(data).encode()) > 48000:
            raise ValueError("Agent history exceeds the 48 KB context limit; review and condense before continuing")
        reservation = engine.reserve_cost("openai:" + role["id"], max_cost_per_call)
        try:
            result = api.structured(role["instructions"] + " Return the required schema; preserve the current script unless your role edits it. Never add sources outside supplied evidence.", data, RESULT_SCHEMA)
        except Exception:
            # A failure may follow a billable refusal. Keep the reservation until reconciliation.
            raise
        content = result["data"]
        if not set(content.get("source_urls", [])) <= allowed_urls:
            raise ValueError("Agent introduced an unsupplied source; draft rejected")
        history.append({"role": role["id"], "result": content, "usage": result.get("usage", {}), "cost_reservation_id": reservation, "reserved_estimate_usd": max_cost_per_call})
        data = {"original_brief": brief, "history": history}
    draft = history[-1]["result"]
    screen = editorial_check(draft["script"], brief["sources"], [j["script"] for j in engine.list_jobs()])
    if draft["decision"] != "accept" or not screen["passed"]:
        return {"accepted": False, "history": history, "screen": screen}
    job = engine.create_job(draft["title"], brief.get("theme", ""), sources=brief["sources"])
    engine.set_research(job["id"], brief["sources"], json.dumps({"evidence": brief["evidence"], "history": history}))
    job = engine.set_script(job["id"], draft["script"])
    return {"accepted": True, "job": job, "screen": screen, "history": history}


def analytics_summary(engine):
    records = engine.metrics_report()
    return {"data": records, "note": "No live performance data until accounts are connected and posts are verified. Missing metrics are unavailable, never synthetic."}
