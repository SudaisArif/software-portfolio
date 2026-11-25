"""Responses structured output + file transcription. Contract tested; not connected."""
import json
import mimetypes
import os
from pathlib import Path
import secrets
from .http import Transport, credential, IntegrationBlocked


class OpenAI:
    def __init__(self, transport=None):
        self.transport = transport or Transport()

    def structured(self, instructions, data, schema, name="agent_result"):
        model = credential("OPENAI_MODEL")
        if model not in {"gpt-5.4-mini", "gpt-5.4-mini-2026-03-17"}:
            raise IntegrationBlocked("Model has no reviewed cost profile; approve pricing and update the allowlist first")
        if len((instructions + json.dumps(data) + json.dumps(schema)).encode()) > 64000:
            raise IntegrationBlocked("Request exceeds the 64 KB text budget")
        result = self.transport.request("POST", "https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + credential("OPENAI_API_KEY")}, paid=True,
            payload={"model": model, "store": False, "service_tier": "default",
                     "instructions": instructions,
                     "input": json.dumps(data), "max_output_tokens": 2400,
                     "text": {"format": {"type": "json_schema", "name": name,
                                          "strict": True, "schema": schema}}})
        if result.get("status") != "completed":
            raise IntegrationBlocked("Model response incomplete; no draft accepted")
        parts = [c for item in result.get("output", []) for c in item.get("content", [])]
        if any(p.get("type") == "refusal" for p in parts):
            raise IntegrationBlocked("Model declined the request; review manually")
        content = "".join(p.get("text", "") for p in parts if p.get("type") == "output_text")
        return {"data": json.loads(content), "usage": result.get("usage", {}),
                "response_id": result.get("id")}

    def transcribe(self, path):
        path = Path(path)
        if path.suffix.lower() not in {".mp3", ".mp4", ".ogg", ".wav", ".webm", ".m4a", ".flac", ".mpeg", ".mpga"}:
            raise ValueError("Unsupported audio format")
        if not path.is_file() or path.stat().st_size > 25_000_000:
            raise ValueError("Audio must be a file under 25 MB")
        boundary = "media-" + secrets.token_hex(20)
        model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe")
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"feedback{path.suffix.lower()}\"\r\n"
                f"Content-Type: {mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}\r\n\r\n").encode()
        body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        result = self.transport.request("POST", "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": "Bearer " + credential("OPENAI_API_KEY"),
                     "Content-Type": "multipart/form-data; boundary=" + boundary}, raw=body, paid=True)
        if not isinstance(result.get("text"), str):
            raise IntegrationBlocked("No transcript returned")
        return result
