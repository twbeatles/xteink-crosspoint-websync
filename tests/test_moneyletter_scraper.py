"""MoneyLetterScraper — 이메일형 중첩 테이블 → e-ink 선형 HTML 변환 단위 테스트."""

from bs4 import BeautifulSoup

from websync.scrapers.moneyletter import MoneyLetterScraper


def _sample_email_html() -> str:
    """Stibee 스타일 중첩 테이블 본문 축소 샘플."""
    return """
    <div class="elementor-widget-theme-post-content">
      <div class="elementor-widget-container">
        <table><tr><td>
          <table><tr><td>
            <div>⏰ 오늘의 요약</div>
            <ul>
              <li><span>첫 번째 브리핑 문장입니다. 충분히 긴 내용.</span></li>
              <li><span>두 번째 브리핑 문장입니다. 충분히 긴 내용.</span></li>
            </ul>
            <p><span>본문 단락이 여기에 들어갑니다. e-ink에서도 보여야 합니다.</span></p>
            <table><tr><td></td></tr></table>
            <div><a href="https://example.com/subscribe">구독하기</a></div>
          </td></tr></table>
        </td></tr></table>
      </div>
    </div>
    """


def test_to_eink_html_flattens_nested_tables():
    sc = MoneyLetterScraper()
    soup = BeautifulSoup(_sample_email_html(), "lxml")
    container = soup.select_one(
        ".elementor-widget-theme-post-content .elementor-widget-container"
    )
    assert container is not None

    sc._clean_content(container, {"include_images": False})
    out = sc._to_eink_html(container)

    assert "<table" not in out.lower()
    assert "<td" not in out.lower()
    text = BeautifulSoup(out, "lxml").get_text(" ", strip=True)
    assert "첫 번째 브리핑" in text
    assert "본문 단락이 여기에" in text
    assert "구독하기" not in text  # CTA 제거
    assert out.count("<p>") >= 2


def test_is_detail_url_vs_archive():
    sc = MoneyLetterScraper()
    assert sc._is_detail_url("https://uppity.co.kr/newsletter/money-letter/") is False
    assert sc._is_detail_url("https://uppity.co.kr/newsletter/money-letter/2/") is False
    assert sc._is_detail_url("https://uppity.co.kr/some-article-slug/") is True
    assert sc._is_detail_url("https://uppity.co.kr/category/foo/") is False
