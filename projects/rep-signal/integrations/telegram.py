"""Private review messages and signed, revision-bound callback decisions."""
import hashlib
import hmac
from .http import Transport, credential, IntegrationBlocked


class Telegram:
    def __init__(self, transport=None):
        self.transport = transport or Transport()

    def call(self, method, payload):
        if method not in {"sendMessage", "getUpdates", "answerCallbackQuery", "getFile"}:
            raise ValueError("Unsupported bot operation")
        result = self.transport.request("POST", "https://api.telegram.org/bot" + credential("TELEGRAM_BOT_TOKEN") + "/" + method,
                                        payload=payload)
        if not result.get("ok"):
            raise IntegrationBlocked("Telegram rejected the operation")
        return result["result"]

    def sign(self, job_id, revision, action):
        payload = f"{job_id}:{revision}:{action}"
        signature = hmac.new(credential("TELEGRAM_BOT_TOKEN").encode(), payload.encode(), hashlib.sha256).hexdigest()[:12]
        result = payload + ":" + signature
        if len(result.encode()) > 64:
            raise ValueError("Callback exceeds Telegram limit")
        return result

    def send_review(self, job):
        buttons = [[{"text": title, "callback_data": self.sign(job["id"], job["revision"], action)}
                    for title, action in [("Approve script", "a"), ("Reject", "r"), ("Request revision", "v")]]]
        text = f"SCRIPT REVIEW · revision {job['revision']}\n{job['title']}\n\n{job['script']}\n\nScript approval does not authorize publishing."
        if len(text) > 4000:
            raise ValueError("Script too long for a review message")
        return self.call("sendMessage", {"chat_id": credential("TELEGRAM_CHAT_ID"), "text": text,
                                        "reply_markup": {"inline_keyboard": buttons}})

    def accept_callback(self, update, engine):
        query = update.get("callback_query", {})
        if str(query.get("from", {}).get("id")) != credential("TELEGRAM_USER_ID") or str(query.get("message", {}).get("chat", {}).get("id")) != credential("TELEGRAM_CHAT_ID"):
            raise IntegrationBlocked("Telegram sender not authorized")
        try:
            job_id, rev, action, signature = query["data"].split(":")
            revision = int(rev)
            if action not in {"a", "r", "v"} or not hmac.compare_digest(query["data"], self.sign(job_id, revision, action)):
                raise ValueError()
        except (ValueError, KeyError):
            raise IntegrationBlocked("Invalid callback signature") from None
        result = engine.review_script(job_id, {"a":"approve", "r":"reject", "v":"revise"}[action],
                                      actor="telegram-owner", revision=revision,
                                      feedback="Revision requested in Telegram" if action == "v" else "")
        self.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": "Decision recorded"})
        return result
