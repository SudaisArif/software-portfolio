"""Bridge from the durable engine to Buffer's asynchronous delivery API."""
from datetime import datetime, timezone, timedelta
import time
from .buffer import Buffer
from .http import credential, IntegrationBlocked
from media_engine import RetryablePublishError


class BufferPublisher:
    def __init__(self, platform, media_urls, adapter=None):
        self.platform = platform
        self.media_urls = media_urls
        self.adapter = adapter or Buffer()

    @property
    def account_id(self):
        return credential("BUFFER_" + self.platform.upper() + "_CHANNEL_ID")

    def publish(self, job, idempotency_key):
        # idempotency_key is an engine claim, not a fictitious Buffer API capability.
        record = self.media_urls.get(job["artifact_sha256"])
        if not isinstance(record,dict) or record.get("sha256") != job["artifact_sha256"] or record.get("expires_at",0) < time.time()+3600 or not record.get("storage_verified"):
            raise RetryablePublishError("Approved media needs a current, verified storage mapping with at least one hour remaining")
        url = record["url"]
        caption = job["title"] + "\n\nOriginal training reflection. Synthetic narration. #training #consistency"
        payload = self.adapter.payload(self.platform, self.account_id,
                                       job["title"], caption, url,
                                       (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
        # Only known local preflight failures are safe to retry. Remote failures stay uncertain.
        try:
            receipt = self.adapter.create(payload)
        except IntegrationBlocked as exc:
            raise RetryablePublishError("Publishing preflight is not authorized or configured") from None
        return {"status": "SUBMITTED", "external_id": receipt["remote_id"], "verified": False}

    def verify(self, external_id):
        result = self.adapter.verify(external_id)
        return {"verified": result["verified"], "external_id": external_id,
                "status": "PUBLISHED" if result["verified"] else "FAILED" if result.get("has_error") or result.get("provider_status") == "error" else "PENDING", "url": result.get("url")}
