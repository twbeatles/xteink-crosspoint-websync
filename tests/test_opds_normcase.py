from unittest.mock import MagicMock

from websync.servers.opds import OPDSHandler


class DummyCtx:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.api_key = ""
        self.require_auth = False


def test_opds_serve_file_normcase_drive_letters(tmp_path):
    # 테스트용 임시 EPUB 파일 생성
    epub_file = tmp_path / "test_book.epub"
    epub_file.write_bytes(b"PK\x03\x04dummy epub content")

    out_dir_str = str(tmp_path)
    ctx = DummyCtx(out_dir_str)

    # OPDSHandler 인스턴스 모킹
    handler = OPDSHandler.__new__(OPDSHandler)
    handler.path = "/opds/download/test_book.epub"
    handler.headers = {}
    handler.server = ctx

    responses = []
    headers_sent = {}

    handler.send_response = lambda code: responses.append(code)
    handler.send_header = lambda k, v: headers_sent.update({k: v})
    handler.end_headers = lambda: None
    handler.send_error = lambda code, msg="": responses.append(code)

    mock_wfile = MagicMock()
    handler.wfile = mock_wfile

    # _serve_file 실행 시 os.path.normcase 적용 덕분에 403이 아니라 200 OK를 응답해야 함
    handler._serve_file()

    assert 200 in responses
    assert 403 not in responses
    assert headers_sent.get("Content-Type") == "application/epub+zip"
