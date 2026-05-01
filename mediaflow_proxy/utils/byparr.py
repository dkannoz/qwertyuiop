"""Byparr (FlareSolverr-compatible) client used as a Cloudflare-bypass fallback."""

import asyncio
import logging

import aiohttp

from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)


class ByparrError(Exception):
    """Raised when a Byparr request fails."""


async def fetch_via_byparr(url: str, post_data: str | None = None) -> str:
    """Fetch *url* through Byparr and return the response body.

    Caller must guard with `if settings.byparr_url:` — this function raises
    ByparrError immediately when BYPARR_URL is not configured.
    """
    if not settings.byparr_url:
        raise ByparrError("BYPARR_URL not set")

    endpoint = f"{settings.byparr_url.rstrip('/')}/v1"
    payload = {
        "cmd": "request.post" if post_data else "request.get",
        "url": url,
        "maxTimeout": settings.byparr_timeout * 1000,
    }
    if post_data:
        payload["postData"] = post_data

    client_timeout = aiohttp.ClientTimeout(total=settings.byparr_timeout + 15)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(endpoint, json=payload) as resp:
                if resp.status != 200:
                    raise ByparrError(f"Byparr HTTP {resp.status}")
                data = await resp.json()
    except asyncio.TimeoutError as e:
        raise ByparrError("Byparr timeout") from e
    except aiohttp.ClientError as e:
        raise ByparrError(f"Byparr network error: {e}") from e

    if data.get("status") != "ok":
        raise ByparrError(f"Byparr: {data.get('message', 'unknown')}")

    return (data.get("solution") or {}).get("response", "")
