"""WebSync 공통 타입 정의"""
from typing import Callable, TypedDict

# 콜백 타입 정의
LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


class ArticleDict(TypedDict, total=False):
    """스크래퍼가 반환하는 기사 딕셔너리 타입"""
    title: str
    content: str
    url: str
    summary_html: str


class PipelineResult(TypedDict, total=False):
    """동기화 파이프라인 결과 타입"""
    status: str
    success: bool
    message: str
    success_count: int
    partial_count: int
    actual_work_sites: int
    site_errors: int
    empty_fetch_sites: int


class SiteConfig(TypedDict, total=False):
    """사이트 설정 타입"""
    name: str
    type: str
    url: str
    item_selector: str
    title_selector: str
    content_selector: str
    link_selector: str  # 아이템 내 상세 URL (기본 a[href])
    remove_selectors: str
    limit: int
    enabled: bool
    include_images: bool
    translate_to: str
    fetch_detail_page: bool
