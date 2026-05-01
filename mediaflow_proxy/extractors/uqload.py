import logging
import re
from typing import Dict, Any
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession

from mediaflow_proxy.configs import settings
from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

logger = logging.getLogger(__name__)

_SOURCE_RE = re.compile(r'sources:\s*\["(https?://[^"]+)"')


class UqloadExtractor(BaseExtractor):
    """Uqload URL extractor.

    Uses curl_cffi + Chrome impersonation to handle Cloudflare protection.
    Follows redirects automatically (uqload.bz/co/io all redirect to uqload.is).
    Falls back to Byparr (when BYPARR_URL is set) if curl_cffi cannot extract.
    """

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        proxy = self._get_proxy(url)
        matched_url: str | None = None
        final_url: str = url
        primary_exc: Exception | None = None

        try:
            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    impersonate="chrome",
                    timeout=30,
                    allow_redirects=True,
                    **({"proxy": proxy} if proxy else {}),
                )
            if response.status_code < 400:
                m = _SOURCE_RE.search(response.text)
                if m:
                    matched_url = m.group(1)
                    final_url = str(response.url)
            if not matched_url:
                primary_exc = ExtractorError(
                    f"Uqload direct fetch: HTTP {response.status_code}, no source pattern match"
                )
        except Exception as e:
            primary_exc = e

        if not matched_url and settings.byparr_url:
            from mediaflow_proxy.utils.byparr import fetch_via_byparr, ByparrError

            try:
                html = await fetch_via_byparr(url)
                m = _SOURCE_RE.search(html)
                if m:
                    matched_url = m.group(1)
                    logger.info("Uqload: Byparr fallback succeeded for %s", url)
                else:
                    logger.warning("Uqload: Byparr fetched %s but no source pattern", url)
            except ByparrError as e:
                logger.warning("Uqload: Byparr fallback failed for %s: %s", url, e)
                primary_exc = e

        if not matched_url:
            raise primary_exc or ExtractorError("Uqload: video URL not found in page source")

        self.base_headers["referer"] = urljoin(final_url, "/")
        return {
            "destination_url": matched_url,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
