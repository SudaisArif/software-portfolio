"""Small injectable HTTPS transport with redacted errors and no automatic POST retries."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class IntegrationBlocked(RuntimeError):
    pass


class RemoteError(RuntimeError):
    def __init__(self, status, uncertain=False):
        self.status = status
        self.uncertain = uncertain
        super().__init__(f"Remote request failed ({status}); reconcile before retrying a mutation")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RemoteError(code, uncertain=True)


class Transport:
    """Only approved hosts; environment switches are deployment controls, not user consent."""
    hosts = {"api.openai.com", "api.elevenlabs.io", "api.telegram.org", "api.buffer.com"}

    def request(self, method, url, headers=None, payload=None, raw=None, paid=False):
        if os.getenv("ALLOW_EXTERNAL_REQUESTS") != "true":
            raise IntegrationBlocked("External requests are disabled; account authorization required")
        if paid and os.getenv("ALLOW_PAID_APIS") != "true":
            raise IntegrationBlocked("Paid API use is disabled; spending approval required")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in self.hosts or parsed.username or parsed.port not in (None,443):
            raise IntegrationBlocked("Endpoint is not an approved HTTPS API")
        body = json.dumps(payload).encode() if payload is not None else raw
        h = {"Accept": "application/json", **(headers or {})}
        if payload is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
                content = response.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024:
                    raise RemoteError("response too large", uncertain=method != "GET")
                return json.loads(content)
        except urllib.error.HTTPError as exc:
            # Do not expose response bodies, authorization headers, or token-bearing URLs.
            # Closing also prevents response-destructor warnings from emitting provider text.
            try:exc.close()
            except OSError:pass
            raise RemoteError(exc.code, uncertain=exc.code >= 500) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RemoteError("transport", uncertain=method != "GET") from None


def credential(name):
    value = os.getenv(name, "")
    if not value:
        raise IntegrationBlocked(f"Missing {name}; configure it securely outside chat")
    return value
