#!/usr/bin/env python3
"""한국 웹사이트 스크래퍼 실사이트 스모크 검증.

공개·비로그인 샘플 URL에 대해 fetch_articles()를 호출하고
목록/본문 품질 기준을 검사합니다.

사용:
  python scripts/validate_korean_scrapers.py
  python scripts/validate_korean_scrapers.py --only naver,tistory,brunch
  python scripts/validate_korean_scrapers.py --json output/scraper_validation.json

주의:
  - 네트워크 필요. CI 기본 스위트에는 넣지 마세요.
  - 대량 수집용이 아니며 검증용 샘플만 사용합니다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from websync.scrapers.factory import ScraperFactory  # noqa: E402

# 검증용 공개 샘플 (limit=1~2, 저작물 재배포 목적 아님)
DEFAULT_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "naver",
        "name": "네이버 블로그 (ranto28)",
        "type": "naver",
        "url": "https://blog.naver.com/ranto28",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "tistory",
        "name": "티스토리 (jojoldu — 기술 블로그)",
        "type": "tistory",
        "url": "https://jojoldu.tistory.com",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "brunch",
        "name": "브런치 (공개 작가 샘플)",
        "type": "brunch",
        # brunch 메인 큐레이션이 아닌 작가 페이지 — 검증 시 깨지면 교체
        "url": "https://brunch.co.kr/@brunch",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "soonsal",
        "name": "순살브리핑",
        "type": "soonsal",
        "url": "https://soonsal.com/newsletters/",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "moneyletter",
        "name": "머니레터 (어피티)",
        "type": "moneyletter",
        "url": "https://uppity.co.kr/newsletter/money-letter/",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "rss_hani",
        "name": "한겨레 RSS (rss)",
        "type": "rss",
        "url": "https://www.hani.co.kr/rss/",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "rss_velog",
        "name": "Velog RSS 샘플",
        "type": "rss",
        "url": "https://v2.velog.io/rss/@velopert",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "velog",
        "name": "Velog 전용 타입",
        "type": "velog",
        "url": "https://velog.io/@velopert",
        "limit": 2,
        "include_images": False,
    },
    {
        "id": "newneek",
        "name": "뉴닉",
        "type": "newneek",
        "url": "https://newneek.co/@newneek",
        "limit": 2,
        "include_images": False,
    },
    # naver_post / naver_cafe 는 공개 채널 변동이 커서 optional 로 분리
    {
        "id": "naver_post",
        "name": "네이버 포스트 (선택)",
        "type": "naver_post",
        "url": "https://post.naver.com/my.naver?memberNo=201",
        "limit": 2,
        "include_images": False,
        "optional": True,
    },
    {
        "id": "naver_cafe",
        "name": "네이버 카페 (선택·공개 카페)",
        "type": "naver_cafe",
        # 구조 검증용 — 이미지 전용 글이 많아 limit≥2 권장
        "url": "https://cafe.naver.com/steamindiegame",
        "limit": 2,
        "include_images": False,
        "min_text": 40,  # 짧은 일상 글 허용
        "optional": True,
    },
]

MIN_TEXT_LEN = 80


@dataclass
class ArticleCheck:
    title: str
    url: str
    text_len: int
    has_script: bool
    ok: bool
    reason: str = ""


@dataclass
class SampleResult:
    id: str
    name: str
    type: str
    url: str
    optional: bool
    status: str  # pass | fail | error | skip
    article_count: int = 0
    skipped_stats: int = 0
    elapsed_sec: float = 0.0
    error: str = ""
    articles: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _text_len(html: str) -> int:
    if not html:
        return 0
    return len(BeautifulSoup(html, "lxml").get_text(" ", strip=True))


def _has_script_or_style(html: str) -> bool:
    if not html:
        return False
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.find("script") or soup.find("style"))


def check_article(art: dict[str, Any], min_text: int = MIN_TEXT_LEN) -> ArticleCheck:
    title = (art.get("title") or "").strip()
    url = (art.get("url") or "").strip()
    content = art.get("content") or ""
    tlen = _text_len(content)
    has_ss = _has_script_or_style(content)

    if not title:
        return ArticleCheck(title, url, tlen, has_ss, False, "제목 없음")
    if not url:
        return ArticleCheck(title, url, tlen, has_ss, False, "URL 없음")
    if tlen < min_text:
        return ArticleCheck(
            title, url, tlen, has_ss, False, f"본문 텍스트 {tlen}자 < {min_text}"
        )
    return ArticleCheck(title, url, tlen, has_ss, True)


def validate_sample(
    sample: dict[str, Any], min_text: int = MIN_TEXT_LEN
) -> SampleResult:
    sid = sample["id"]
    optional = bool(sample.get("optional"))
    sample_min = int(sample.get("min_text", min_text) or min_text)
    result = SampleResult(
        id=sid,
        name=sample.get("name", sid),
        type=sample["type"],
        url=sample["url"],
        optional=optional,
        status="fail",
    )
    site_config = {
        "name": sample.get("name", sid),
        "type": sample["type"],
        "url": sample["url"],
        "limit": sample.get("limit", 2),
        "include_images": sample.get("include_images", False),
        "enabled": True,
    }
    # css 타입 선택자 전달
    for key in (
        "item_selector",
        "title_selector",
        "content_selector",
        "remove_selectors",
        "fetch_detail_page",
    ):
        if key in sample:
            site_config[key] = sample[key]

    t0 = time.perf_counter()
    try:
        scraper = ScraperFactory.get_scraper(sample["type"])
        articles = scraper.fetch_articles(site_config)
        stats = getattr(scraper, "last_fetch_stats", None) or {}
        result.skipped_stats = int(stats.get("skipped", 0) or 0)
        result.article_count = len(articles or [])
        result.elapsed_sec = round(time.perf_counter() - t0, 2)

        if not articles:
            result.status = "fail"
            result.reasons.append("기사 0건")
            return result

        ok_count = 0
        for art in articles:
            chk = check_article(art, min_text=sample_min)
            result.articles.append(asdict(chk))
            if chk.ok:
                ok_count += 1
            else:
                result.reasons.append(f"{chk.title[:40]!r}: {chk.reason}")

        # 1건 이상 품질 통과면 샘플 성공 (일부 짧은 글 허용)
        if ok_count >= 1:
            result.status = "pass"
            if ok_count < len(articles):
                result.reasons.append(
                    f"부분 통과: {ok_count}/{len(articles)}건 품질 기준 충족"
                )
        else:
            result.status = "fail"
        return result
    except Exception as e:
        result.elapsed_sec = round(time.perf_counter() - t0, 2)
        result.status = "error"
        result.error = f"{type(e).__name__}: {e}"
        result.reasons.append(result.error)
        return result


def _filter_samples(
    samples: list[dict], only: set[str] | None, include_optional: bool
) -> list[dict]:
    out = []
    for s in samples:
        if only and s["id"] not in only and s["type"] not in only:
            continue
        if s.get("optional") and not include_optional:
            continue
        out.append(s)
    return out


def print_report(results: list[SampleResult]) -> None:
    print()
    print("=" * 88)
    print(f"{'ID':<14} {'TYPE':<12} {'STATUS':<8} {'N':>3} {'SEC':>6}  NAME")
    print("-" * 88)
    for r in results:
        flag = r.status.upper()
        if r.optional and r.status != "pass":
            flag = f"{flag}*"
        print(
            f"{r.id:<14} {r.type:<12} {flag:<8} {r.article_count:>3} {r.elapsed_sec:>6.2f}  {r.name}"
        )
        if r.articles:
            for a in r.articles:
                mark = "OK" if a.get("ok") else "NG"
                title = (a.get("title") or "")[:48]
                print(f"    [{mark}] {a.get('text_len', 0):>5}자  {title}")
        if r.reasons:
            for reason in r.reasons[:5]:
                print(f"    · {reason}")
        if r.error and r.error not in r.reasons:
            print(f"    · {r.error}")
    print("=" * 88)

    hard = [r for r in results if not r.optional]
    opt = [r for r in results if r.optional]
    hard_pass = sum(1 for r in hard if r.status == "pass")
    opt_pass = sum(1 for r in opt if r.status == "pass")
    print(
        f"필수: {hard_pass}/{len(hard)} 통과  |  선택: {opt_pass}/{len(opt)} 통과  (* = optional 실패는 exit code 무시)"
    )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="한국 웹사이트 스크래퍼 실사이트 검증")
    parser.add_argument(
        "--only",
        default="",
        help="쉼표 구분 id 또는 type (예: naver,tistory,brunch)",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="naver_post, naver_cafe 등 optional 샘플 포함",
    )
    parser.add_argument(
        "--min-text",
        type=int,
        default=MIN_TEXT_LEN,
        help=f"본문 최소 텍스트 길이 (기본 {MIN_TEXT_LEN})",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default="",
        help="결과 JSON 저장 경로",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="샘플 간 대기 초 (예의 있는 요청 간격)",
    )
    args = parser.parse_args(argv)

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    samples = _filter_samples(DEFAULT_SAMPLES, only, args.include_optional)
    if not samples:
        print(
            "검증할 샘플이 없습니다. --only / --include-optional 을 확인하세요.",
            file=sys.stderr,
        )
        return 2

    print(f"검증 시작: {len(samples)}개 샘플 (min_text={args.min_text})")
    results: list[SampleResult] = []
    for i, sample in enumerate(samples):
        print(f"  → [{sample['id']}] {sample['type']} {sample['url']} ...", flush=True)
        results.append(validate_sample(sample, min_text=args.min_text))
        if i < len(samples) - 1 and args.delay > 0:
            time.sleep(args.delay)

    print_report(results)

    if args.json_path:
        path = Path(args.json_path)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "min_text": args.min_text,
            "results": [asdict(r) for r in results],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 저장: {path}")

    # optional 실패는 전체 실패로 치지 않음
    hard_fail = any(r.status != "pass" and not r.optional for r in results)
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
