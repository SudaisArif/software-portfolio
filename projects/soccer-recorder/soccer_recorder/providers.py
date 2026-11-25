from __future__ import annotations

from urllib.parse import urlparse

from .boxcast import BoxCastAdapter
from .flo import FloCollegeAdapter
from .hudl import HudlAdapter


def provider_key_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold()
    if host == "flocollege.com" or host.endswith(".flocollege.com"):
        return "flocollege"
    if host == "flofc.com" or host.endswith(".flofc.com"):
        return "flocollege"
    if host == "boxcast.tv" or host.endswith(".boxcast.tv"):
        return "boxcast"
    if host == "api.boxcast.com" or host.endswith(".api.boxcast.com"):
        return "boxcast"
    return "hudl"


def adapter_for_url(url: str) -> HudlAdapter | FloCollegeAdapter | BoxCastAdapter:
    provider = provider_key_for_url(url)
    if provider == "flocollege":
        return FloCollegeAdapter()
    if provider == "boxcast":
        return BoxCastAdapter()
    return HudlAdapter()
