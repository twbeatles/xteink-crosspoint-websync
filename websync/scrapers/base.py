"""스크래퍼 공통 기반 및 유틸리티"""
import re
import requests
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:
    Retry = None  # urllib3 미설치 시 폴백

from websync.core.article import ensure_article_url
from websync.i18n import t

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 스크래퍼 GET 본문 상한 (메모리 폭주 방지)
FETCH_MAX_BYTES = 16 * 1024 * 1024
FETCH_MAX_REDIRECTS = 5

# 사이트 설정 limit 기본·범위 (설정 검증은 권고 수준이므로 스크래퍼 진입점에서 clamp)
LIMIT_DEFAULT = 5
LIMIT_MIN = 1
LIMIT_MAX = 100


def normalize_limit(value, default: int = LIMIT_DEFAULT) -> int:
    """사이트 설정 limit을 정수로 정규화합니다 (실패 시 default, 1~100 clamp)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(LIMIT_MIN, min(LIMIT_MAX, number))


def is_allowed_fetch_url(url: str) -> bool:
    """스크래핑용 URL은 http(s) + 호스트가 있을 때만 허용."""
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


def _build_session() -> requests.Session:
    """연결 풀링 + 자동 재시도가 설정된 requests.Session 생성."""
    session = requests.Session()
    kwargs = {"pool_connections": 20, "pool_maxsize": 20}
    if Retry is not None:
        kwargs["max_retries"] = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
    adapter = HTTPAdapter(**kwargs)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# 모듈 수준 공유 세션 (연결 재사용)
_session = _build_session()


def fetch_url(url: str, headers: dict | None = None, timeout: int = 15) -> requests.Response:
    """재시도 세션을 통해 HTTP GET 요청을 수행합니다.

    모든 스크래퍼는 이 헬퍼를 사용하여 일시적 네트워크 오류에 대한
    자동 재시도(최대 3회, 백오프 0.5초) 및 연결 풀링을 활용합니다.
    http(s)만 허용하며 본문은 FETCH_MAX_BYTES 를 넘으면 실패합니다.
    """
    if not is_allowed_fetch_url(url):
        raise ValueError(t("scraper.https_only", url=(url or "")[:80]))
    merged = dict(HEADERS)
    if headers:
        merged.update(headers)
    # Follow redirects explicitly so a public URL cannot bounce a scraper into
    # localhost or a private network.  An explicitly configured private URL is
    # still allowed (the selector UI asks the user to confirm those sources).
    from websync.scrapers.selector_assistant.url_safety import is_private_or_local_url

    current_url = url
    allow_private_chain = is_private_or_local_url(url)
    resp = None
    redirect_codes = {301, 302, 303, 307, 308}
    for redirect_count in range(FETCH_MAX_REDIRECTS + 1):
        resp = _session.get(
            current_url,
            headers=merged,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        if resp.status_code not in redirect_codes or not resp.headers.get("Location"):
            break
        if redirect_count >= FETCH_MAX_REDIRECTS:
            resp.close()
            raise ValueError("Too many HTTP redirects")
        next_url = urljoin(current_url, resp.headers["Location"])
        resp.close()
        if not is_allowed_fetch_url(next_url):
            raise ValueError(t("scraper.https_only", url=next_url[:80]))
        if not allow_private_chain and is_private_or_local_url(next_url):
            raise ValueError("Public scraper URL redirected to a private/local address")
        current_url = next_url

    if resp is None:  # defensive; the loop always executes at least once
        raise ValueError("HTTP request did not produce a response")
    cl = resp.headers.get("Content-Length")
    size_err = t("scraper.size_limit", limit=FETCH_MAX_BYTES)
    try:
        if cl is not None and int(cl) > FETCH_MAX_BYTES:
            resp.close()
            raise ValueError(size_err)
    except (TypeError, ValueError) as e:
        if str(e) == size_err:
            raise
    body = bytearray()
    try:
        for chunk in resp.iter_content(64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > FETCH_MAX_BYTES:
                resp.close()
                raise ValueError(t("scraper.size_limit", limit=FETCH_MAX_BYTES))
    except Exception:
        resp.close()
        raise
    resp._content = bytes(body)
    resp._content_consumed = True
    return resp


def maybe_strip_images(element, site_config: dict):
    if site_config.get("include_images", False):
        return
    for img in element.find_all("img"):
        img.decompose()


def extract_rss_link(item, feed_url: str) -> str:
    link_elem = item.find("link")
    if not link_elem:
        return ""
    href = link_elem.get("href")
    if href:
        return href.strip()
    return (link_elem.text or "").strip()


class BaseScraper(ABC):
    @abstractmethod
    def fetch_articles(self, site_config: dict) -> list:
        pass
