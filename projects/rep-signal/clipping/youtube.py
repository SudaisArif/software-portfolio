"""Official YouTube Data API metadata. Never downloads video or public transcripts."""
import json
import os
import re
from datetime import datetime,timezone
import urllib.parse
import urllib.request
import urllib.error
from integrations.http import IntegrationBlocked,NoRedirect,credential


class YouTubeMetadata:
    def __init__(self,fetch=None):self.fetch=fetch or self._fetch
    def _fetch(self,resource,params):
        if os.getenv("ALLOW_EXTERNAL_REQUESTS")!="true":raise IntegrationBlocked("YouTube metadata requests are disabled")
        if resource not in {"search","videos"}:raise ValueError("Unsupported metadata resource")
        query=urllib.parse.urlencode({**params,"key":credential("YOUTUBE_API_KEY")})
        request=urllib.request.Request("https://www.googleapis.com/youtube/v3/"+resource+"?"+query,headers={"Accept":"application/json"})
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
                raw=response.read(8_000_001)
                if len(raw)>8_000_000:raise ValueError("YouTube metadata response too large")
                return json.loads(raw)
        except (urllib.error.URLError,TimeoutError,OSError):
            raise IntegrationBlocked("YouTube metadata request failed; inspect quota/account configuration without logging credentials") from None
    def discover(self,query,limit=10,creative_commons_only=True):
        if not isinstance(query,str) or not 1<=len(query.strip())<=200 or isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=25:
            raise ValueError("Supply a focused query and 1–25 results")
        params={"part":"snippet","type":"video","q":query,"maxResults":limit,"order":"viewCount","videoDuration":"long"}
        if creative_commons_only:params["videoLicense"]="creativeCommon"
        search=self.fetch("search",params)
        ids=[item.get("id",{}).get("videoId","") for item in search.get("items",[])]
        ids=[video_id for video_id in ids if re.fullmatch(r"[A-Za-z0-9_-]{11}",video_id)][:limit]
        if not ids:return {"candidates":[],"observed_at":datetime.now(timezone.utc).isoformat(),"scope":"No source media or captions downloaded"}
        items=self.fetch("videos",{"part":"snippet,contentDetails,statistics,status","id":",".join(ids)}).get("items",[])
        now=datetime.now(timezone.utc).isoformat()
        candidates=[]
        for item in items:
            if item.get("id") not in ids:continue
            snippet=item.get("snippet",{});statistics=item.get("statistics",{})
            measured={key:int(statistics[key]) if str(statistics.get(key,"")).isdigit() else None for key in ("viewCount","likeCount","commentCount")}
            candidates.append({"video_id":item["id"],"source_url":"https://www.youtube.com/watch?v="+item["id"],"title":snippet.get("title"),"creator":snippet.get("channelTitle"),"channel_id":snippet.get("channelId"),"published_at":snippet.get("publishedAt"),"duration_iso8601":item.get("contentDetails",{}).get("duration"),"measured_counts":measured,"counts_observed_at":now,"license_label":item.get("status",{}).get("license"),"rights_status":"unverified","virality_verified":False,"reason":"High view-count search result; permission, context and clip performance still unverified"})
        return {"candidates":candidates,"observed_at":now,"scope":"Official API metadata only. A Creative Commons label is a lead, not validation of every incorporated asset or permission to obtain a media file through an unsupported downloader."}
