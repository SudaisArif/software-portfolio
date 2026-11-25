"""Buffer GraphQL API. A queued post is never represented as a published post.

Verified against developers.buffer.com/reference.html on 2026-11-13.
Buffer does not document an idempotency key: never retry an uncertain createPost.
"""
import os
import urllib.parse
from .http import Transport, credential, IntegrationBlocked, RemoteError

CREATE = """mutation($input:CreatePostInput!){createPost(input:$input){__typename ... on PostActionSuccess{post{id status dueAt}} ... on MutationError{message}}}"""
GET = """query($input:PostInput!){post(input:$input){id status sentAt externalLink error{message}}}"""
CHANNELS = """query($input:ChannelsInput!){channels(input:$input){id name service isDisconnected isLocked isQueuePaused}}"""
ORGANIZATIONS = "query{account{organizations{id name}}}"


class Buffer:
    def __init__(self, transport=None):
        self.transport = transport or Transport()

    def query(self, query, variables=None):
        result = self.transport.request("POST", "https://api.buffer.com",
            headers={"Authorization": "Bearer " + credential("BUFFER_API_KEY")},
            payload={"query": query, "variables": variables or {}})
        if result.get("errors"):
            raise RemoteError("GraphQL error", uncertain=query.startswith("mutation"))
        return result.get("data", {})

    def organizations(self):
        return self.query(ORGANIZATIONS)

    def channels(self, organization_id):
        return self.query(CHANNELS, {"input": {"organizationId": organization_id}})

    @staticmethod
    def payload(platform, channel_id, title, caption, video_url, due_at):
        url = urllib.parse.urlsplit(video_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Buffer requires an HTTPS media URL reachable until delivery")
        metadata = {
            "youtube": {"youtube": {"title": title[:100], "categoryId": "17", "privacy": "public", "madeForKids": False, "isAiGenerated": True}},
            "instagram": {"instagram": {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": True}},
            "tiktok": {"tiktok": {"isAiGenerated": True}},
        }
        if platform not in metadata:
            raise ValueError("Unsupported publishing platform")
        return {"channelId": channel_id, "text": caption,
                "assets": [{"video": {"url": video_url}}], "schedulingType": "automatic",
                "mode": "customScheduled", "dueAt": due_at,
                "needsApproval": False, "saveToDraft": False, "aiAssisted": True,
                "metadata": metadata[platform]}

    def create(self, payload):
        if os.getenv("ALLOW_PUBLISHING") != "true":
            raise IntegrationBlocked("Publishing is disabled; release approval and account authorization required")
        data = self.query(CREATE, {"input": payload}).get("createPost", {})
        if data.get("__typename") != "PostActionSuccess" or not data.get("post", {}).get("id"):
            raise RemoteError("Buffer mutation rejected or unrecognized", uncertain=True)
        post = data["post"]
        return {"remote_id": post["id"], "status": "pending", "verified": False,
                "provider_status": post.get("status")}

    def verify(self, remote_id):
        post = self.query(GET, {"input": {"id": remote_id}}).get("post")
        if not post or post.get("id") != remote_id:
            raise RemoteError("post missing", uncertain=True)
        published = post.get("status") == "sent" and bool(post.get("sentAt")) and bool(post.get("externalLink"))
        return {"remote_id": remote_id, "status": "published" if published else "pending",
                "verified": published, "url": post.get("externalLink") if published else None,
                "published_at": post.get("sentAt") if published else None,
                "provider_status": post.get("status"), "has_error": bool(post.get("error"))}
