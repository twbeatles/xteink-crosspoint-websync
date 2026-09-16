"""선택자 도우미 데이터 클래스."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class SelectorSample:
    text: str
    html_preview: str = ""


@dataclass
class SelectorTestResult:
    count: int
    samples: list[SelectorSample] = field(default_factory=list)
    error: str = ""


@dataclass
class DomNode:
    """DOM 아웃라인용 플랫/트리 노드 (부모 index로 연결)."""
    index: int
    parent_index: int  # -1 = root
    tag: str
    label: str
    css_path: str
    text_preview: str
    depth: int


@dataclass
class FeedInfo:
    url: str
    title: str = ""
    feed_type: str = "rss"
    source: str = "link"  # link | path_probe | guess


@dataclass
class PageAnalysis:
    url: str
    base_url: str
    title: str = ""
    feeds: list[FeedInfo] = field(default_factory=list)
    platform: Optional[str] = None
    suggestions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    outline: list[DomNode] = field(default_factory=list)
    error: str = ""
    html: str = ""
    # 튜닝 결과 메타
    recommend_mode: str = "css"  # rss | platform | css
    fetch_detail_recommended: bool = False
    recommended_site: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
