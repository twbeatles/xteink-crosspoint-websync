# 개발자 가이드

일반 사용법은 [USER_GUIDE.md](USER_GUIDE.md), 저장소 개요는 루트 [README.md](../README.md)를 보세요.  
이 문서는 **코드 구조·테스트·빌드** 등 개발 시 참고 내용입니다.

아키텍처·기능 확장 로드맵의 더 긴 설명은 루트 `CLAUDE.md`를 참고하세요.

---

## 1. 모듈 구성

```
xteink-x3-websync/
├── x3_websync.py              # 진입점 (CLI/GUI, 단일 인스턴스 락)
├── websync/                  # 메인 패키지
│   ├── core/                 # paths, article, logger, process_lock
│   ├── config/               # ConfigManager, validator
│   ├── db/                   # SyncHistoryDb
│   ├── scrapers/             # 스크래퍼 + factory + 한국 프리셋
│   ├── epub/                 # builder + css/cover/sanitize + themes/
│   ├── upload/               # uploader, device_client, host, remote_path
│   ├── pipeline/             # service 파사드 + sync/preview/selected
│   ├── backup/               # 공유 데이터 폴더 정본 (sites.json + synced_posts.json)
│   ├── integrations/         # Calibre, ToastNotifier
│   ├── scheduler/            # schtasks / launchd / crontab
│   ├── servers/              # OPDS + web dashboard
│   ├── watch/                # Calibre 폴더 감시
│   └── gui/                  # app_core, sync_tab, device_files, settings_tab …
├── tests/                    # pytest
├── scripts/                  # 마이그레이션·실사이트 검증 등
└── docs/                     # 사용자·개발 문서
```

| 패키지 | 역할 |
|--------|------|
| `x3_websync.py` | 진입점 — GUI / `--sync` / `--smoke`(핵심 모듈 import 검증) |
| `websync.core` | 경로, 로깅, 프로세스 락, 기사 URL 유틸 |
| `websync.config` | `config.json` CRUD, 검증, secrets 마스킹 유틸 |
| `websync.pipeline` | 동기화·프리뷰·선택 전송 오케스트레이션 (`upload_results` 공통 헬퍼) |
| `websync.scrapers` | 사이트별 수집기 + `ScraperFactory` + 프리셋 |
| `websync.epub` | EPUB 빌드 (테마·표지·정제) |
| `websync.upload` | 무선 업로드, 기기 파일 API |
| `websync.db` | 전송 이력 SQLite |
| `websync.backup` | OneDrive 등 폴더 미러 (sites/이력) |
| `websync.gui` | CustomTkinter GUI |
| `websync.scheduler` | OS 스케줄 등록 |
| `websync.servers` | OPDS · 웹 대시보드 |
| `websync.watch` | Calibre 폴더 감시 |

---

## 2. 스크래퍼 타입

현재 등록 타입은 `websync/scrapers/types.py` 의 `SCRAPER_TYPES` 가 단일 기준입니다.  
GUI·validator·factory 가 이 목록을 공유합니다.

| 타입 | 모듈 | 비고 |
|------|------|------|
| `css` | `css.py` | 사용자 CSS 선택자 (`link_selector`, 상세 본문 폴백, 폴백 통계) |
| (도우미) | `selector_assistant.py` | 페이지 분석·선택자 추천·RSS 프로브·사설 URL 감지 (GUI 비의존) |
| (GUI) | `gui/sync_tab/selector_wizard.py` | 사이트 등록 시 분석/테스트/미리보기 패널 (스레드 안전) |
| `rss` | `rss.py` | RSS/Atom |
| `velog` | `velog.py` | 프로필 URL → Velog RSS |
| `naver` | `naver.py` | 네이버 블로그 |
| `tistory` | `tistory.py` | 티스토리 RSS + 본문 |
| `brunch` | `brunch.py` | 브런치 API + 본문 |
| `newneek` | `newneek.py` | 뉴닉 사이트맵 + `__NEXT_DATA__` |
| `youtube` | `youtube.py` | 자막 (선택 의존성) |
| `substack` | `substack.py` | Substack |
| `naver_cafe` | `naver_cafe.py` | 공개 카페 |
| `naver_post` | `naver_post.py` | **서비스 종료** (명확한 예외) |
| `soonsal` | `soonsal.py` | 순살브리핑 |
| `moneyletter` | `moneyletter.py` | 어피티 머니레터 |

한국 추천 프리셋: `websync/scrapers/presets.py`  
새 스크래퍼 추가 절차는 `CLAUDE.md` §6 참고.

### 실사이트 스모크 검증

외부 네트워크 필요. **CI 기본 스위트에는 넣지 마세요.**

```bash
python scripts/validate_korean_scrapers.py
python scripts/validate_korean_scrapers.py --only naver,tistory,brunch,velog,newneek
python scripts/validate_korean_scrapers.py --include-optional --json output/scraper_validation.json
```

픽스처 기반 회귀 테스트(네트워크 없음):

```bash
python -m pytest tests/test_scraper_fixtures.py tests/test_brunch_scraper.py -q
```

---

## 3. 실행·설정 동작 요약

| 항목 | 동작 |
|------|------|
| X3 주소 | IP 또는 `crosspoint.local` |
| 다중 기기 | GUI 등록, IP·표시 이름 중복 불가 |
| 기기 파일 | File Transfer 모드; `device_files.default_upload_path` 가 뉴스/Calibre 업로드에도 적용 |
| 동기화 이력 | URL + `device_ip` 단위, 성공 기기만 기록 |
| 부분 재시도 | 미수신 기기만 재업로드 |
| GUI ↔ `--sync` | 프로세스 파일 락으로 직렬화 |
| 프리뷰/선택 동기화 | 동일 파이프라인 락 사용(`service._try_acquire_pipeline_locks`). 백업 pull → 처리 순서로 정본 일치 |
| 웹 대시보드 동기화 | `begin_sync_pipeline_async` — 락 선점 후 수락/거부를 즉시 반환 (`POST /api/sync` → 202/409). 취소는 `POST /api/cancel` → `request_cancel()` |
| 동기화 취소 | GUI **취소** 또는 `SyncService.request_cancel()` — 사이트 경계에서 중단 (`status=cancelled`) |
| 프로세스 락 경로 | `PROJECT_ROOT/x3_websync_pipeline.lock` (휴대용 다중 설치가 서로 막히지 않음) |
| 스크래핑 URL | `fetch_url` 은 http(s)만 허용, 본문 16MB 상한. 잘못된 스킴 사이트는 파이프라인에서 스킵 |
| 번역 | 전역 `translation.enabled` 가 꺼져 있으면 사이트 `translate_to` 도 무시 |
| 웹/OPDS 서버 | `ThreadingHTTPServer` 기반 — 동시 요청 블로킹 없음 |
| daily_digest 합본 | 합본 전용 카운터(`digest_success`/`digest_partial`)로 판정; per_site 카운터와 분리 |
| 기기 0대 | 파이프라인 시작 시 `no_targets` 로 실패 (무의미한 스크래핑 방지) |
| 레거시 이력 `*` | 동기화 시작 시 기본 기기로 `remap_legacy_star_to_device` |
| config 충돌 | GUI `_safe_save_config` 는 revision CAS + 병합 재시도(최대 3회) |
| AI 요약·번역 실패 | 주입된 `service.logger` 로 warning 노출(조용한 스킵 지양) |

### 보안·프라이버시

- **OPDS**: 기본 localhost 무인증. LAN 공개 시 API 키 필수 (Bearer / `X-Api-Key`). 쿼리 `?api_key=` 는 기본 비활성 (`X3_OPDS_ALLOW_QUERY_API_KEY=1` 로만 허용). OPDS/웹 서버는 `ThreadingHTTPServer` 기반으로 동시 요청을 처리한다.
- **웹 대시보드 LAN**: HTTP 평문 — 신뢰 네트워크에서만. 동기화 트리거 API는 인증 필수.
- **AI 요약·번역**: 기사 본문이 외부 API로 전송될 수 있음. 키는 `config.json` 로컬 저장(gitignore). 표시 마스킹: `websync.config.secrets.mask_secret` — 설정 탭에서는 기본 `****` 표시, “표시” 토글로만 전체 노출. 호출 실패는 주입된 `service.logger` 로 warning 출력된다.

---

## 4. 의존성

| 구분 | 내용 |
|------|------|
| 필수 | `requirements.txt` — requests, beautifulsoup4, lxml, ebooklib, customtkinter, cryptography 등 |
| 선택 | `requirements-optional.txt` — Pillow, googletrans, youtube-transcript-api, watchdog |
| 외부 | Calibre (`calibredb`) — 서재 연동 시 |

Python 3.10+ 권장.

---

## 5. 테스트

```bash
python -m pytest tests/ -q --tb=short -ra
```

주요 영역: config, db, pipeline, scrapers(픽스처), epub, uploader, servers, process_lock, backup, scheduler 등.  
정확한 수는 `pytest --collect-only -q` 로 확인 (2026-08-19 감사 개선 반영 후 260+).

### 허메틱(격리) 규칙 — CI 재발 방지

단위 테스트는 **GitHub Actions 클린 체크아웃**에서도 동일하게 통과해야 합니다.

| 하지 말 것 | 대신 할 것 |
|-----------|-----------|
| `dist/`, `output/`, `logs/`, 로컬 `config.json`, `*.db` 등 **gitignore 경로** 필수 가정 | `tempfile` / `tests/fixtures/` 에 스키마 샘플 작성 |
| 개발 PC 에만 있는 배포 사이드카(`synced_posts.json`, `*설정백업*.json`) 읽기 | 동일 JSON 스키마를 테스트 코드·픽스처로 인라인 |

가드 테스트: `tests/test_hermetic_suite.py` — 테스트 소스가 `dist/` 등을 하드코딩하면 실패합니다.

---

## 6. Windows EXE 빌드 (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --clean x3_websync.spec
```

결과: `dist/x3_websync.exe` (GUI, 콘솔 없음).

빌드 후 `dist/x3_websync.exe --smoke`를 실행하여 핵심 모듈이 frozen 환경에서 로드되는지 확인합니다. 종료 코드가 0이 아니면 배포하지 않습니다.

EXE는 실행 파일과 같은 폴더에 `config.json`, `sync_history.db`, `logs/`, `output/` 을 둡니다.

공유 데이터 폴더(`portable_data` / 하위 호환 `backup_sync`): 사이트·이력 **정본**은 OneDrive 등 폴더의 `sites.json` + `synced_posts.json` 입니다. 두 파일은 삭제 tombstone을 포함하며, 로컬 `sync_history.db` 는 작업 캐시이므로 클라우드 경로에 직접 두지 마세요. 이력 모드 `history_mode`: `per_device` | `global_url`.

**로컬 사이드카 이어받기** (`websync/backup/local_import.py`): 실행 폴더의 `synced_posts.json`, `sites.json`, `*설정백업*.json`(kind 없는 레거시 sites export 포함)을 앱 기동 시 `import_posts_union` / `merge_sites` 로 반영합니다.  
기기별 이력은 안정 기기 ID와 명시적 `alias_keys`로만 동일 기기를 판정합니다. 단일 기기라는 이유만으로 다른 기기의 URL 이력을 완료로 간주하지 않습니다.

**스펙에서 제외되는 선택 기능** (`x3_websync.spec` excludes):

| 기능 | 제외 패키지 | 소스 실행 시 |
|------|-------------|--------------|
| EPUB 표지 이미지 | Pillow | optional 설치 |
| YouTube 자막 | youtube-transcript-api | 동일 |
| Calibre Watch | watchdog | 동일 |
| googletrans 번역 | googletrans | 동일 |

새 스크래퍼·GUI 서브모듈 추가 시 `x3_websync.spec` 의 `hiddenimports` 에 모듈을 넣어야 합니다.  
업데이트 UI는 `websync.gui.settings_tab.updater` 입니다.

---

## 7. 자동 업데이트 & 릴리즈 워크플로우

### 보안 서명 모델 (Ed25519)
- **비대칭키 서명**: 빌드된 바이너리(`xteink-x3-websync-vX.Y.Z.exe`)의 SHA-256 해시 및 메타데이터에 대해 Ed25519 개인키로 디지털 서명된 `latest.json` 매니페스트를 생성합니다.
- **공개키 내장**: `websync/core/update_constants.py`의 `UPDATE_PUBLIC_KEY_B64_DEFAULT`에 공개키가 안전하게 내장되어 있으며, 개인키는 오직 GitHub Actions Secret(`X3_UPDATE_PRIVATE_KEY_B64`)으로만 관리됩니다.
- **안전 검증 체계**:
  1. 원격 매니페스트 다운로드 시 CDN 캐시 우회(`Cache-Control: no-cache` + 타임스탬프 파라미터).
  2. Ed25519 서명, HTTPS URL, SHA-256 해시, 크기 상한(500MB), 만료일 무결성 검증.
  3. 실시간 스트리밍 해시 검증 및 다운로드 취소(`cancel_event`) 지원.
  4. 이전 버전 자동 백업(`.bak`) 및 `--smoke`(핵심 모듈 import) 실패 시 자동 롤백.

### 배포 절차 (GitHub Actions)
1. `websync/__init__.py`의 `__version__ = "X.Y.Z"` 업데이트 및 커밋.
2. Git 태그 생성 및 푸시:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
3. GitHub Actions `.github/workflows/release.yml`이 자동으로:
   - pytest 실행 및 키 검증 (`scripts/verify_update_release_key.py`)
   - PyInstaller 윈도우 단일 바이너리 빌드 및 `--smoke` 체크
   - Ed25519 서명 매니페스트 생성 (`scripts/build_update_manifest.py`)
   - GitHub Release 생성 및 바이너리/매니페스트 업로드
   - `main` 브랜치의 `updates/latest.json` 자동 갱신 커밋 & 푸시 (`[skip ci]`)

---

## 8. 관련 문서

| 문서 | 용도 |
|------|------|
| [USER_GUIDE.md](USER_GUIDE.md) | 사용자 화면·설정 |
| [FEATURE_PROPOSALS.md](FEATURE_PROPOSALS.md) | 기능 제안 |
| [PROJECT_AUDIT.md](PROJECT_AUDIT.md) | 구버전 감사 아카이브 |
| 루트 [`PROJECT_AUDIT.md`](../PROJECT_AUDIT.md) | 최신 구현 감사 |
| `CLAUDE.md` (루트) | 전체 구조·확장 가이드 |
| `x3_websync.spec` | PyInstaller hiddenimports (스크래퍼 모듈 누락 주의) |
