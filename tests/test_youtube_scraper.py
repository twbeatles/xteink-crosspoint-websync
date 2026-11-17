"""YouTube 자막 API 0.6 / 1.x 호환 래퍼."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from websync.scrapers.youtube import YoutubeScraper


def test_fetch_transcript_segments_legacy_get_transcript():
    fake = [{"text": "안녕"}, {"text": "하세요"}]

    class _Legacy:
        @staticmethod
        def get_transcript(video_id, languages=None):
            return fake

    mod = MagicMock()
    mod.YouTubeTranscriptApi = _Legacy
    with patch.dict(sys.modules, {"youtube_transcript_api": mod}):
        segs = YoutubeScraper._fetch_transcript_segments("vid", ["ko"])
    assert segs == fake


def test_fetch_transcript_segments_v1_fetch():
    snippet = SimpleNamespace(text="hello")

    class _V1:
        def fetch(self, video_id, languages=None):
            return [snippet]

    mod = MagicMock()
    mod.YouTubeTranscriptApi = _V1
    with patch.dict(sys.modules, {"youtube_transcript_api": mod}):
        segs = YoutubeScraper._fetch_transcript_segments("vid", ["en"])
    assert segs[0]["text"] == "hello"
