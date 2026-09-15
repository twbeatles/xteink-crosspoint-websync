"""한국 콘텐츠 추천 사이트 프리셋.

GUI 사이트 등록 대화상자의 프리셋 드롭다운과
문서/검증 스크립트에서 공유합니다.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SitePreset(TypedDict, total=False):
    label: str
    label_key: str
    name: str
    type: str
    url: str
    limit: int
    include_images: bool
    note: str
    note_key: str


# label 은 GUI 표시용. 선택 시 name/type/url/limit 을 폼에 채움.
KOREAN_SITE_PRESETS: list[SitePreset] = [
    {
        "label": "(직접 입력)",
        "label_key": "preset.custom",
        "name": "",
        "type": "css",
        "url": "",
        "limit": 5,
    },
    {
        "label": "Velog 작가 (velopert)",
        "label_key": "preset.velog_velopert",
        "name": "Velog · velopert",
        "type": "velog",
        "url": "https://velog.io/@velopert",
        "limit": 3,
        "note": "내부적으로 Velog RSS 사용",
        "note_key": "preset.note.velog_rss",
    },
    {
        "label": "Velog RSS (직접)",
        "label_key": "preset.velog_rss",
        "name": "Velog RSS",
        "type": "rss",
        "url": "https://v2.velog.io/rss/@velopert",
        "limit": 3,
    },
    {
        "label": "한겨레 RSS",
        "label_key": "preset.hani",
        "name": "한겨레",
        "type": "rss",
        "url": "https://www.hani.co.kr/rss/",
        "limit": 5,
        "note": "요약·이미지 위주 피드일 수 있음",
        "note_key": "preset.note.hani",
    },
    {
        "label": "티스토리 · 기억보단 기록을",
        "label_key": "preset.tistory_jojoldu",
        "name": "jojoldu 티스토리",
        "type": "tistory",
        "url": "https://jojoldu.tistory.com",
        "limit": 3,
    },
    {
        "label": "브런치 · 브런치팀",
        "label_key": "preset.brunch_team",
        "name": "브런치팀",
        "type": "brunch",
        "url": "https://brunch.co.kr/@brunch",
        "limit": 3,
    },
    {
        "label": "뉴닉 (공식)",
        "label_key": "preset.newneek",
        "name": "뉴닉",
        "type": "newneek",
        "url": "https://newneek.co/@newneek",
        "limit": 3,
        "note": "사이트맵 기반 최신 글 수집",
        "note_key": "preset.note.newneek",
    },
    {
        "label": "순살브리핑",
        "label_key": "preset.soonsal",
        "name": "순살브리핑",
        "type": "soonsal",
        "url": "https://soonsal.com/newsletters/",
        "limit": 2,
    },
    {
        "label": "머니레터 (어피티)",
        "label_key": "preset.moneyletter",
        "name": "머니레터",
        "type": "moneyletter",
        "url": "https://uppity.co.kr/newsletter/money-letter/",
        "limit": 2,
    },
    {
        "label": "토스 기술 블로그",
        "label_key": "preset.toss",
        "name": "토스 기술 블로그",
        "type": "rss",
        "url": "https://toss.tech/rss.xml",
        "limit": 3,
    },
    {
        "label": "카카오 기술 블로그",
        "label_key": "preset.kakao",
        "name": "카카오 기술 블로그",
        "type": "rss",
        "url": "https://tech.kakao.com/feed/",
        "limit": 3,
    },
    {
        "label": "우아한형제들 기술 블로그",
        "label_key": "preset.woowahan",
        "name": "우아한형제들 기술 블로그",
        "type": "rss",
        "url": "https://techblog.woowahan.com/feed/",
        "limit": 3,
    },
    {
        "label": "라인 엔지니어링",
        "label_key": "preset.line",
        "name": "라인 엔지니어링",
        "type": "rss",
        "url": "https://engineering.linecorp.com/ko/feed/",
        "limit": 3,
    },
    {
        "label": "뱅크샐러드 블로그 (RSS)",
        "label_key": "preset.banksalad",
        "name": "뱅크샐러드 블로그",
        "type": "rss",
        "url": "https://blog.banksalad.com/rss.xml",
        "limit": 3,
    },
    {
        "label": "네이버 D2 (RSS)",
        "label_key": "preset.naver_d2",
        "name": "NAVER D2",
        "type": "rss",
        "url": "https://d2.naver.com/d2.atom",
        "limit": 3,
        "note": "홈은 SPA — RSS/Atom 권장",
        "note_key": "preset.note.naver_d2",
    },
    {
        "label": "CSS 직접설정 (선택자 도우미)",
        "label_key": "preset.css_manual",
        "name": "",
        "type": "css",
        "url": "",
        "limit": 5,
        "note": "전용 타입·RSS가 없을 때 — 페이지 분석으로 선택자 자동 추천",
        "note_key": "preset.note.css_manual",
    },
]


def preset_display_label(preset: SitePreset) -> str:
    """현재 UI 언어의 프리셋 표시명."""
    from websync.i18n import t

    key = (preset.get("label_key") or "").strip()
    if key:
        translated = t(key)
        if translated != key:
            return translated
    return preset.get("label") or ""


def preset_labels() -> list[str]:
    return [preset_display_label(p) for p in KOREAN_SITE_PRESETS]


def get_preset_by_label(label: str) -> SitePreset | None:
    for p in KOREAN_SITE_PRESETS:
        if p.get("label") == label or preset_display_label(p) == label:
            return p
    return None


def preset_as_site_config(preset: SitePreset) -> dict[str, Any]:
    """프리셋을 sites[] 항목 형태로 변환."""
    return {
        "name": preset.get("name") or preset.get("label", "preset"),
        "type": preset.get("type", "rss"),
        "url": preset.get("url", ""),
        "limit": int(preset.get("limit", 5) or 5),
        "enabled": True,
        "include_images": bool(preset.get("include_images", False)),
    }
