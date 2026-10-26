"""한국 콘텐츠 추천 사이트 프리셋.

GUI 사이트 등록 대화상자의 프리셋 드롭다운과
문서/검증 스크립트에서 공유합니다.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SitePreset(TypedDict, total=False):
    label: str
    label_key: str
    category: str
    name: str
    type: str
    url: str
    limit: int
    include_images: bool
    note: str
    note_key: str


# 카테고리 선택 → 프리셋 선택 2단계 UI 용. (key, i18n key). category 가 없는
# 프리셋(직접 입력·CSS 직접설정)은 어느 카테고리에서나 항상 보인다.
PRESET_CATEGORIES: list[tuple[str, str]] = [
    ("tech", "preset.category.tech"),
    ("blog", "preset.category.blog"),
    ("life", "preset.category.life"),
    ("global", "preset.category.global"),
]

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
        "category": "blog",
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
        "category": "blog",
        "name": "Velog RSS",
        "type": "rss",
        "url": "https://v2.velog.io/rss/@velopert",
        "limit": 3,
    },
    {
        "label": "티스토리 · 기억보단 기록을",
        "label_key": "preset.tistory_jojoldu",
        "category": "blog",
        "name": "jojoldu 티스토리",
        "type": "tistory",
        "url": "https://jojoldu.tistory.com",
        "limit": 3,
    },
    {
        "label": "브런치 · 브런치팀",
        "label_key": "preset.brunch_team",
        "category": "blog",
        "name": "브런치팀",
        "type": "brunch",
        "url": "https://brunch.co.kr/@brunch",
        "limit": 3,
    },
    {
        "label": "뉴닉 (공식)",
        "label_key": "preset.newneek",
        "category": "blog",
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
        "category": "blog",
        "name": "순살브리핑",
        "type": "soonsal",
        "url": "https://soonsal.com/newsletters/",
        "limit": 2,
    },
    {
        "label": "머니레터 (어피티)",
        "label_key": "preset.moneyletter",
        "category": "blog",
        "name": "머니레터",
        "type": "moneyletter",
        "url": "https://uppity.co.kr/newsletter/money-letter/",
        "limit": 2,
    },
    {
        "label": "토스 기술 블로그",
        "label_key": "preset.toss",
        "category": "tech",
        "name": "토스 기술 블로그",
        "type": "rss",
        "url": "https://toss.tech/rss.xml",
        "limit": 3,
    },
    {
        "label": "카카오 기술 블로그",
        "label_key": "preset.kakao",
        "category": "tech",
        "name": "카카오 기술 블로그",
        "type": "rss",
        "url": "https://tech.kakao.com/feed/",
        "limit": 3,
        "note": "요약 위주 피드 — 본문이 짧을 수 있음",
        "note_key": "preset.note.summary_feed",
    },
    {
        "label": "우아한형제들 기술 블로그",
        "label_key": "preset.woowahan",
        "category": "tech",
        "name": "우아한형제들 기술 블로그",
        "type": "rss",
        "url": "https://techblog.woowahan.com/feed/",
        "limit": 3,
    },
    {
        "label": "라인 엔지니어링",
        "label_key": "preset.line",
        "category": "tech",
        "name": "라인 엔지니어링",
        "type": "rss",
        "url": "https://engineering.linecorp.com/ko/feed/",
        "limit": 3,
        "note": "요약 위주 피드 — 본문이 짧을 수 있음",
        "note_key": "preset.note.summary_feed",
    },
    {
        "label": "뱅크샐러드 블로그 (RSS)",
        "label_key": "preset.banksalad",
        "category": "tech",
        "name": "뱅크샐러드 블로그",
        "type": "rss",
        "url": "https://blog.banksalad.com/rss.xml",
        "limit": 3,
        "note": "요약 위주 피드 — 본문이 짧을 수 있음",
        "note_key": "preset.note.summary_feed",
    },
    {
        "label": "네이버 D2 (RSS)",
        "label_key": "preset.naver_d2",
        "category": "tech",
        "name": "NAVER D2",
        "type": "rss",
        "url": "https://d2.naver.com/d2.atom",
        "limit": 3,
        "note": "홈은 SPA — RSS/Atom 권장",
        "note_key": "preset.note.naver_d2",
    },
    {
        "label": "당근 테크 블로그",
        "label_key": "preset.daangn",
        "category": "tech",
        "name": "당근 테크 블로그",
        "type": "rss",
        "url": "https://medium.com/feed/daangn",
        "limit": 3,
    },
    {
        "label": "쿠팡 엔지니어링",
        "label_key": "preset.coupang",
        "category": "tech",
        "name": "쿠팡 엔지니어링",
        "type": "rss",
        "url": "https://medium.com/feed/coupang-engineering",
        "limit": 3,
    },
    {
        "label": "무신사 테크",
        "label_key": "preset.musinsa",
        "category": "tech",
        "name": "무신사 테크",
        "type": "rss",
        "url": "https://medium.com/feed/musinsa-tech",
        "limit": 3,
    },
    {
        "label": "네이버 클라우드 블로그",
        "label_key": "preset.naver_cloud",
        "category": "tech",
        "name": "네이버 클라우드",
        "type": "rss",
        "url": "https://medium.com/feed/naver-cloud-platform",
        "limit": 3,
    },
    {
        "label": "하이퍼커넥트 기술 블로그",
        "label_key": "preset.hyperconnect",
        "category": "tech",
        "name": "하이퍼커넥트 기술 블로그",
        "type": "rss",
        "url": "https://hyperconnect.github.io/feed.xml",
        "limit": 3,
    },
    {
        "label": "여기어때 기술 블로그",
        "label_key": "preset.gccompany",
        "category": "tech",
        "name": "여기어때 기술 블로그",
        "type": "rss",
        "url": "https://techblog.gccompany.co.kr/feed",
        "limit": 3,
    },
    {
        "label": "NHN Cloud 밋업",
        "label_key": "preset.nhn_cloud",
        "category": "tech",
        "name": "NHN Cloud 밋업",
        "type": "rss",
        "url": "https://meetup.nhncloud.com/rss",
        "limit": 3,
    },
    {
        "label": "데브시스터즈 기술 블로그",
        "label_key": "preset.devsisters",
        "category": "tech",
        "name": "데브시스터즈 기술 블로그",
        "type": "rss",
        "url": "https://tech.devsisters.com/rss.xml",
        "limit": 3,
    },
    {
        "label": "리멤버 기술 블로그",
        "label_key": "preset.remember",
        "category": "tech",
        "name": "리멤버 기술 블로그",
        "type": "rss",
        "url": "https://tech.remember.co.kr/feed",
        "limit": 3,
    },
    {
        "label": "토스 피드",
        "label_key": "preset.toss_feed",
        "category": "tech",
        "name": "토스 피드",
        "type": "rss",
        "url": "https://blog.toss.im/rss.xml",
        "limit": 3,
    },
    {
        "label": "요즘IT",
        "label_key": "preset.yozmit",
        "category": "tech",
        "name": "요즘IT",
        "type": "rss",
        "url": "https://yozm.wishket.com/magazine/feed/",
        "limit": 3,
    },
    {
        "label": "디에디트 (IT·리뷰)",
        "label_key": "preset.theedit",
        "category": "life",
        "name": "디에디트",
        "type": "rss",
        "url": "https://the-edit.co.kr/feed",
        "limit": 3,
    },
    {
        "label": "디자인프레스",
        "label_key": "preset.design_press",
        "category": "life",
        "name": "디자인프레스",
        "type": "rss",
        "url": "https://www.design.co.kr/rss",
        "limit": 3,
    },
    {
        "label": "GQ Korea",
        "label_key": "preset.gq_korea",
        "category": "life",
        "name": "GQ Korea",
        "type": "rss",
        "url": "https://www.gqkorea.co.kr/feed/",
        "limit": 3,
    },
    {
        "label": "Vogue Korea",
        "label_key": "preset.vogue_korea",
        "category": "life",
        "name": "Vogue Korea",
        "type": "rss",
        "url": "https://www.vogue.co.kr/feed/",
        "limit": 3,
    },
    {
        "label": "게임메카",
        "label_key": "preset.gamemeca",
        "category": "life",
        "name": "게임메카",
        "type": "rss",
        "url": "https://www.gamemeca.com/rss.php",
        "limit": 3,
    },
    {
        "label": "어피티 블로그 (재테크)",
        "label_key": "preset.uppity_blog",
        "category": "life",
        "name": "어피티 블로그",
        "type": "rss",
        "url": "https://uppity.co.kr/feed/",
        "limit": 3,
    },
    {
        "label": "The Marginalian (에세이·영문)",
        "label_key": "preset.marginalian",
        "category": "global",
        "name": "The Marginalian",
        "type": "rss",
        "url": "https://www.themarginalian.org/feed/",
        "limit": 3,
        "note": "영어 원문 — 사이트 옵션의 번역으로 한국어 변환 가능",
        "note_key": "preset.note.english_source",
    },
    {
        "label": "Open Culture (문화·영문)",
        "label_key": "preset.open_culture",
        "category": "global",
        "name": "Open Culture",
        "type": "rss",
        "url": "https://www.openculture.com/feed",
        "limit": 3,
        "note": "영어 원문 — 사이트 옵션의 번역으로 한국어 변환 가능",
        "note_key": "preset.note.english_source",
    },
    {
        "label": "Dezeen (디자인·건축, 영문)",
        "label_key": "preset.dezeen",
        "category": "global",
        "name": "Dezeen",
        "type": "rss",
        "url": "https://www.dezeen.com/feed/",
        "limit": 3,
        "note": "영어 원문 — 사이트 옵션의 번역으로 한국어 변환 가능",
        "note_key": "preset.note.english_source",
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


def presets_for_category(category: str = "") -> list[SitePreset]:
    """카테고리에 속한 프리셋 (빈 값=전체). 카테고리 없는 프리셋은 항상 포함."""
    if not category:
        return list(KOREAN_SITE_PRESETS)
    return [p for p in KOREAN_SITE_PRESETS if not p.get("category") or p.get("category") == category]


def category_display_label(category: str) -> str:
    """카테고리 키의 표시명 ("" → '전체')."""
    from websync.i18n import t

    key = dict(PRESET_CATEGORIES).get(category, "preset.category.all")
    return t(key)


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
