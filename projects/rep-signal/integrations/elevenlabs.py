"""Narration with authoritative character timing; never clone a real person's voice."""
import base64
import os
from .http import Transport, credential, IntegrationBlocked


class ElevenLabs:
    def __init__(self, transport=None):
        self.transport = transport or Transport()

    def synthesize(self, text):
        voice = credential("ELEVENLABS_VOICE_ID")
        if not voice.isalnum():
            raise ValueError("Invalid voice ID")
        result = self.transport.request("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
            headers={"xi-api-key": credential("ELEVENLABS_API_KEY")}, paid=True,
            payload={"text": text, "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
                     "voice_settings": {"stability": 0.62, "similarity_boost": 0.75, "style": 0.12, "use_speaker_boost": True}})
        alignment = result.get("normalized_alignment") or result.get("alignment")
        if not alignment or not result.get("audio_base64"):
            raise IntegrationBlocked("Narration missing audio or timing data")
        keys = ("characters", "character_start_times_seconds", "character_end_times_seconds")
        if len({len(alignment.get(k, [])) for k in keys}) != 1 or not alignment.get("characters"):
            raise IntegrationBlocked("Invalid narration alignment")
        previous = 0.0
        for start, end in zip(alignment[keys[1]], alignment[keys[2]]):
            if start < previous or end < start:
                raise IntegrationBlocked("Non-monotonic narration timing")
            previous = start
        return base64.b64decode(result["audio_base64"], validate=True), alignment
