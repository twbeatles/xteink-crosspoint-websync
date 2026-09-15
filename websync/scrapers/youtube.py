"""YoutubeScraper"""
from typing import cast

from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, extract_rss_link, ensure_article_url, fetch_url
from bs4 import BeautifulSoup
from websync.i18n import t

class YoutubeScraper(BaseScraper):
    """YouTube 채널 최신 영상의 자막을 수집하여 EPUB으로 변환하는 스크래퍼"""

    def __init__(self):
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        # url은 채널 RSS 피드: https://www.youtube.com/feeds/videos.xml?channel_id=...
        self.last_fetch_stats = {"skipped": 0}
        url = site_config.get("url", "")
        limit = site_config.get("limit", 3)
        articles = []
        skipped = 0
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml-xml")
            entries = soup.find_all("entry")[:limit]
            for entry in entries:
                title_tag = entry.find("title")
                video_id_tag = entry.find("yt:videoId")
                if not title_tag or not video_id_tag:
                    skipped += 1
                    continue
                title = title_tag.get_text(strip=True)
                video_id = video_id_tag.get_text(strip=True)
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                content = self._fetch_transcript(video_id, title)
                if content:
                    articles.append({"title": title, "content": content, "url": video_url})
                else:
                    skipped += 1
            self.last_fetch_stats = {"skipped": skipped}
            if entries and not articles:
                raise Exception(t("youtube.zero_transcript", n=len(entries)))
        except Exception as e:
            msg = str(e)
            if t("youtube.zero_marker") in msg or t("youtube.failed", error="") in msg:
                raise
            raise Exception(t("youtube.failed", error=e)) from e
        return articles

    @staticmethod
    def _fetch_transcript_segments(video_id: str, languages: list) -> list[dict]:
        """youtube-transcript-api 0.6(get_transcript) / 1.x(fetch) 호환."""
        from youtube_transcript_api import YouTubeTranscriptApi

        getter = getattr(YouTubeTranscriptApi, "get_transcript", None)
        if callable(getter):
            return cast(list[dict], getter(video_id, languages=languages))

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=languages)
        out: list[dict] = []
        for seg in fetched:
            if isinstance(seg, dict):
                out.append({"text": seg.get("text") or ""})
            else:
                out.append({"text": getattr(seg, "text", "") or ""})
        return out

    def _fetch_transcript(self, video_id: str, title: str) -> str:
        try:
            for lang in (["ko"], ["en"]):
                try:
                    transcript = self._fetch_transcript_segments(video_id, lang)
                    paragraphs = []
                    chunk = []
                    for seg in transcript:
                        chunk.append(seg.get("text") or "")
                        if len(chunk) >= 10:
                            paragraphs.append("<p>" + " ".join(chunk) + "</p>")
                            chunk = []
                    if chunk:
                        paragraphs.append("<p>" + " ".join(chunk) + "</p>")
                    if paragraphs:
                        return "\n".join(paragraphs)
                except Exception:
                    continue
        except ImportError:
            print(t("youtube.missing_api"))
        except Exception as e:
            print(t("youtube.transcript_failed", video_id=video_id, error=e))
        return ""
