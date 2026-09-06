# CLAUDE.md — 개발자 가이드 & 기능 확장 로드맵

> **Xteink X3 WebSync Manager** 프로젝트의 완전한 구조 분석 및 향후 기능 확장 아이디어를 정리한 내부 개발 문서입니다.  
> 새로운 기능 추가, 버그 수정, 구조 변경 시 이 문서를 먼저 참조하세요.

---

## 1. 프로젝트 개요

**목적**: Xteink X3 (CrossPoint 펌웨어) e-ink 리더기를 위한 통합 뉴스·콘텐츠 수집 → EPUB 빌드 → 무선 전송 자동화 GUI 툴

**핵심 가치**:
- 매일 아침 지정한 뉴스 소스(일반 웹, RSS, 네이버 블로그)를 자동 수집해 e-ink 기기에 최적화된 EPUB 전자책으로 빌드 및 전송
- 이미 보낸 기사는 SQLite DB로 중복 제거 (증분 동기화)
- Calibre 도서관과 연동해 PC 서재의 책을 무선 즉시 전송

**개발 원칙**: SOLID, 모듈 단일 책임, Python 타입 힌트 적용

---

## 2. 프로젝트 파일 구조 전체 분석

```
xteink-x3-websync/
├── x3_websync.py              # 진입점 — CLI/GUI 분기, 단일 인스턴스 락
├── x3_websync.spec            # PyInstaller 빌드 스펙
├── websync/                   # 메인 패키지 (SOLID 기반 역할별 분리)
│   ├── core/
│   │   ├── paths.py           # PROJECT_ROOT (개발: 패키지 상위, frozen: exe 디렉터리)
│   │   ├── process_lock.py    # 크로스 프로세스 파이프라인 파일 락
│   │   ├── article.py         # 기사 URL / synthetic key 유틸
│   │   ├── update_constants.py# 업데이트 URL, Ed25519 공개키 및 제한 상수
│   │   ├── update_manifest.py # Ed25519 서명 검증 및 릴리즈 매니페스트 파싱
│   │   ├── update_installer.py# 스트리밍 다운로드, 교체/롤백, 헬퍼 프로세스
│   │   ├── update_service.py  # 비동기 업데이트 확인/다운로드 조율 서비스
│   │   └── logger.py          # 날짜별 로그 파일
│   ├── config/
│   │   └── manager.py         # config.json CRUD — threading.Lock, deep merge
│   ├── db/
│   │   └── history.py         # SQLite 동기화 이력 — timeout=10.0
│   ├── scrapers/
│   │   ├── base.py / types.py / presets.py   # 공통·타입 상수·한국 추천 프리셋
│   │   ├── selector_assistant.py  # CSS 선택자 도우미(분석·추천·RSS 프로브, GUI 비의존)
│   │   ├── css.py / rss.py / velog.py / naver.py / tistory.py / brunch.py / newneek.py
│   │   ├── youtube.py / substack.py / naver_cafe.py / naver_post.py
│   │   ├── soonsal.py / moneyletter.py / newsletter_base.py
│   │   └── factory.py         # ScraperFactory — 13종 (SCRAPER_TYPES 공유)
│   ├── epub/
│   │   ├── builder.py         # EPUB 빌더 파사드
│   │   ├── css.py / cover.py / sanitize.py  # CSS·표지·본문 정제 (SRP)
│   │   └── themes/            # EPUB CSS 프리셋
│   ├── upload/
│   │   ├── host.py            # 기기 호스트 정규화
│   │   ├── remote_path.py     # 원격 경로 유틸
│   │   ├── sync_epub.py       # 동기화 EPUB 날짜 필터
│   │   ├── errors.py          # DeviceClientError
│   │   ├── uploader.py        # 무선 업로드
│   │   └── device_client.py   # CrossPoint 파일 API 클라이언트
│   ├── pipeline/
│   │   ├── service.py         # SyncService 파사드 (락·설정·백업 훅·위임)
│   │   ├── sync_pipeline.py   # 전체 사이트 동기화 실행
│   │   ├── preview.py         # 프리뷰(스크래핑만, 파이프라인 락 공유)
│   │   ├── selected_sync.py   # 선택 기사 동기화
│   │   ├── article_keys.py    # 기사 URL 키
│   │   ├── summarizer.py      # AI 요약
│   │   └── translator.py      # 번역
│   ├── backup/                # 공유 데이터 폴더 정본 (sites.json + synced_posts.json)
│   │   ├── service.py         # BackupSyncService / PortableDataService pull/push
│   │   ├── portable_cfg.py    # portable_data ↔ backup_sync 호환
│   │   ├── local_import.py    # 실행 폴더 synced_posts·설정백업 JSON 이어받기
│   │   ├── atomic_io.py / format.py
│   ├── integrations/
│   │   ├── calibre.py         # calibredb.exe 래퍼
│   │   └── notifier.py        # 크로스플랫폼 토스트 알림
│   ├── scheduler/
│   │   └── manager.py         # schtasks / launchd / crontab
│   ├── servers/
│   │   ├── opds.py            # OPDS HTTP 서버
│   │   ├── web_dashboard.py   # 하위 호환 re-export → dashboard/
│   │   └── dashboard/         # session, templates_loader, handler, http_server, service
│   ├── watch/
│   │   └── calibre.py         # Calibre 폴더 감시 (watchdog)
│   └── gui/
│       ├── widgets.py         # 공통 위젯 및 테마 색상 상수
│       ├── app_core/          # SyncAppGui (layout/helpers/config_sync/sync_control)
│       ├── sync_tab/          # 뉴스 동기화 탭 (connection/devices/sites/schedule/preview/selector_wizard)
│       ├── device_files/      # 기기 파일 탭 (browser/actions/cleanup/settings)
│       ├── settings_tab/      # 고급 설정 (epub/servers/watch/ai_translation/backup_sync)
│       ├── tab_*.py           # 하위 호환 re-export (sync/device_files/settings)
│       ├── app.py             # 하위 호환 re-export → app_core
│       ├── tab_calibre.py     # Calibre 서재 탭
│       ├── tab_history.py     # 동기화 이력 탭
│       └── bottom_bar.py      # 하단 진행도 및 로그 바

│
├── config.json                # 사용자 설정 (gitignore)
├── sync_history.db            # 전송 이력 DB (gitignore)
├── output/                    # 생성 EPUB (gitignore)
├── logs/                      # 실행 로그 (gitignore)
├── tests/                     # pytest (수집 수는 `pytest --collect-only -q`)
├── scripts/                   # migrate, build/verify update manifest & keys
├── updates/                   # latest.json (Ed25519 서명 릴리즈 매니페스트)
├── requirements.txt           # 필수 + pytest + cryptography
├── requirements-optional.txt  # Pillow, googletrans, youtube, watchdog
├── .github/workflows/
│   ├── test.yml               # CI: pytest
│   └── release.yml            # 자동 릴리즈 (PyInstaller + Ed25519 서명 배포)
├── README.md / CLAUDE.md
├── PROJECT_AUDIT.md           # 최신 기능 구현 감사 (루트)
├── docs/                      # 사용자·개발 문서
│   ├── USER_GUIDE.md          # 사용 설명서
│   ├── DEVELOPER.md           # 모듈·테스트·빌드·스크래퍼 검증
│   ├── FEATURE_PROPOSALS.md
│   └── PROJECT_AUDIT.md       # 구버전 감사 — 최신은 루트 PROJECT_AUDIT.md
├── pyrightconfig.json
└── .gitignore
```

---

## 3. 모듈별 상세 분석

### 3-1. `x3_websync.py` — 진입점

| 항목 | 내용 |
|------|------|
| 역할 | CLI `--sync` 플래그 분기 / GUI 앱 기동 |
| 보안 패치 | `NullWriter` 클래스로 pythonw.exe stdout=None 방어 |
| 다중 실행 방지 | GUI: Windows named mutex + 락 파일 / Unix flock |
| `--sync` 모드 | GUI 락 없이 기동 — `threading.Lock` + **프로세스 파일 락**(`PROJECT_ROOT/x3_websync_pipeline.lock`)으로 직렬화 |
| `--smoke` | 핵심 모듈 import 검증. 성공 0 / 실패 1 (업데이트 롤백 스모크) |
| 주의 | GUI 락은 `finally`에서 항상 해제됨 |

**호출 관계**:
```
main()
  ├── [--smoke] run_smoke_check()
  ├── [GUI만] acquire_instance_lock()
  ├── ConfigManager()
  ├── SyncService(config_manager)
  └── [--sync] service.run_sync_pipeline() → sys.exit(0|1)
      [GUI]   SyncAppGui(service).run()
```

---

### 3-2. `websync/config/manager.py` — 설정 관리자

| 항목 | 내용 |
|------|------|
| 역할 | `config.json` 로드·저장, 결손 키 자동 보강 |
| 동시성 보호 | `threading.Lock()` + config 경로별 `ProcessFileLock` |
| 내부 메서드 | `_save_config_unlocked()` — writer별 고유 tmp+bak+replace, `ConfigLoadError` |
| 스키마 버전 | `config_version` (현재 3), 결손 키 자동 보강 |
| RMW 안전 | `_config_revision` CAS + `update_config(mutator)` / `ConfigConflictError` |

**설정 스키마** (`config.json`):
```json
{
  "config_version": 3,
  "_config_revision": 0,
  "x3_ip": "crosspoint.local",
  "x3_devices": [{"name": "침실", "ip": "192.168.1.20"}],
  "output_dir": "./output",
  "calibre_path": "C:\\Program Files\\Calibre2\\calibredb.exe",
  "calibre_library_path": "",
  "font_family": "serif",
  "font_size": 16,
  "line_height": 1.7,
  "epub_cover": true,
  "portable_data": {
    "enabled": false,
    "folder": "",
    "include_history": true,
    "auto_export": true,
    "auto_import_on_start": true,
    "history_mode": "per_device",
    "wizard_completed": false
  },
  "backup_sync": { "...": "portable_data 와 공통 필드 미러 (하위 호환)" },
  "sites": [
    {
      "name": "사이트명",
      "type": "css | rss | velog | naver | tistory | brunch | newneek | youtube | substack | …",
      "url": "https://...",
      "item_selector": ".post-item",
      "title_selector": ".post-title",
      "link_selector": "a[href]",
      "content_selector": ".post-content",
      "remove_selectors": ".ad, #comments",
      "limit": 5,
      "enabled": true,
      "include_images": false,
      "translate_to": "",
      "fetch_detail_page": false
    }
  ],
  "schedule": {"enabled": false, "hour": "07", "minute": "00"},
  "ai_summary": {"enabled": false, "provider": "openai", "api_key": ""},
  "translation": {"enabled": false, "provider": "googletrans"},
  "opds_server": {"port": 8765, "allow_lan": false, "api_key": ""},
  "web_dashboard": {"port": 8766, "allow_lan": false, "api_token": ""},
  "calibre_watch": {"enabled": false, "watch_dir": ""},
  "device_files": {
    "default_browse_path": "/",
    "default_upload_path": "/",
    "cleanup_older_days": 14,
    "warn_overwrite": true
  }
}
```

---

### 3-3. `websync/pipeline/service.py` — 동기화 파이프라인 오케스트레이터

| 항목 | 내용 |
|------|------|
| 역할 | 스크래핑 → 중복 필터 → EPUB 빌드 → 기기 업로드 전 과정 총괄 |
| 동시성 | `threading.Lock` + `ProcessFileLock` (GUI / `--sync` 프로세스 간 직렬화) |
| 중복 필터 | `needs_sync(url, target_ips)` — 기기 중 하나라도 미전송이면 포함 |
| 재전송 | `upload_to_targets(..., only_ips=pending)` — **미전송 기기만** 업로드 |
| 결과 반환 | `bool` — True: 신규 없음·전체 성공 / False: 오류·부분 실패·이미 실행 중·취소 |
| 취소 | `request_cancel()` — 사이트 경계에서 `status=cancelled` |
| 상태 API | `get_last_pipeline_result()` — 웹 대시보드 `/api/status` 연동 |

**파이프라인 흐름**:
```
run_sync_pipeline()
  0. thread lock + process file lock (비차단, 실패 시 return False)
  1. config 최신 리로드
  2. enabled_sites 필터링
  3. for each site:
     a. ScraperFactory.get_scraper(type).fetch_articles(site)
     b. [신규] = needs_sync(url, target_ips) 필터 (DB 오류 → SyncHistoryDbError 중단)
     c. pending_ips = 배치 내 미전송 기기
     d. (선택) 번역 / AI 요약
     e. EpubBuilder.build → upload_to_targets(only_ips=pending_ips)  # 결과 키=IP
     f. 성공 IP만 mark_synced(..., device_ip=ip)
  4. ToastNotifier.show_toast(결과)
```

---

### 3-4. `websync/scrapers/` — 콘텐츠 수집기 (팩토리 패턴)

| 클래스 | 타입 | 방식 |
|--------|------|------|
| `BaseScraper` | ABC | 추상 기반 클래스 |
| `CssSelectorScraper` | `"css"` | CSS 선택자(`item`/`title`/`link`/`content`); `fetch_detail_page` 시 상세 본문 + 폴백 |
| (도우미) | — | `selector_assistant` + GUI `selector_wizard`: 페이지 분석·RSS 권장·선택자 추천/테스트/미리보기 |
| `RssScraper` | `"rss"` | RSS/Atom XML 파싱 |
| `NaverBlogScraper` | `"naver"` | RSS 리스팅 + PostView.naver iframe 우회 |
| `VelogScraper` | `"velog"` | 프로필 URL → Velog RSS 래퍼 |
| `TistoryScraper` 등 | tistory/brunch/youtube/substack 등 | 전용 수집; 개별 스킵 통계·전량 실패 시 예외 |
| `NewneekScraper` | `"newneek"` | 사이트맵 + `__NEXT_DATA__` 본문 |
| `NaverCafeScraper` | `"naver_cafe"` | 공개 카페 clubid + article API |
| `NaverPostScraper` | `"naver_post"` | **서비스 종료** — 명확한 예외 |
| `SoonsalScraper` / `MoneyLetterScraper` | soonsal / moneyletter | 뉴스레터 아카이브 |
| `ScraperFactory` | — | `.get_scraper(type)` / `SCRAPER_TYPES` (13종) |

**NaverBlogScraper 특이사항**:
- 블로그 ID 추출: `blog.naver.com/ID`, `m.blog.naver.com/ID`, `ID.blog.me` 세 가지 주소 형식 지원
- 본문 추출: `div.se-main-container` (스마트에디터 One) 또는 `#postViewArea` (구버전)
- 서식 박멸: 모든 `style`, `class` 속성 강제 삭제 → 배경색·글자색 초기화
- 이미지 제거: e-ink 최적화를 위해 모든 `img` 태그 decompose

---

### 3-5. `websync/epub/builder.py` — EPUB 빌더

| 항목 | 내용 |
|------|------|
| 역할 | 기사 배열을 받아 단일 EPUB 파일 생성 |
| 의존성 | `ebooklib` (+ 선택 Pillow 표지) |
| 언어 메타 | `lang="ko"` 설정, UTF-8 인코딩 명시 |
| CSS | font/size/line-height **범위·문자 검증** 후 삽입 |
| 본문 | `script`/`style` 태그 제거 |
| 파일명 | `{site_name}_{YYYY-MM-DD}.epub` |

---

### 3-6. `websync/upload/uploader.py` — 기기 무선 업로드

| 항목 | 내용 |
|------|------|
| 역할 | X3 기기의 `/upload` HTTP 엔드포인트로 파일 POST |
| 파일명 | 영숫자·하이픈·언더바만 허용 (CrossPoint 크래시 방지) |
| 결과 | `{ip: bool}` — 기기 **IP/호스트**를 키로 사용 |
| 부분 전송 | `only_ips=[...]` 로 대상 기기 제한 |
| 대상 폴더 | `remote_dir` / `upload_to_targets(..., remote_dir=)` — `device_files.default_upload_path` |
| 타임아웃 | `25초 + (파일크기_MB × 5초)` 동적 계산 |
| 연결 테스트 | `GET /` 3초 타임아웃으로 기기 생존 여부 확인 |

### 3-6b. `websync/upload/device_client.py` — 기기 파일 관리 API

| 항목 | 내용 |
|------|------|
| 역할 | CrossPoint File Transfer REST (`/api/files`, `/delete`, `/rename`, `/move`, …) |
| GUI | `gui/device_files/` — **📁 기기 파일** 탭 |
| 정리 | 파일명 `YYYY-MM-DD` 기반 오래된 동기화 EPUB 후보 선택·일괄 삭제 |
| 설정 | `device_files`: `default_browse_path`, `default_upload_path`, `cleanup_older_days`, `warn_overwrite` |

---

### 3-7. `websync/integrations/calibre.py` — Calibre 연동

| 항목 | 내용 |
|------|------|
| 역할 | `calibredb.exe` CLI 래퍼 |
| `list_books()` | `--to-json` 플래그로 JSON 파싱 |
| `get_book_file_path()` | EPUB > PDF > MOBI > TXT 우선순위로 파일 경로 반환 |

---

### 3-8. `websync/scheduler/manager.py` — 스케줄러

| 항목 | 내용 |
|------|------|
| 역할 | Windows `schtasks` 기반 일간 스케줄 등록/해제 |
| 보안 | `hour/minute` 입력 정수 범위 검증, `shell=False` 인자 리스트 실행 |
| 경로 고정 | `cmd.exe /c "cd /d <project_dir> && pythonw ..."` |

---

### 3-9. `websync/integrations/notifier.py` — 알림

| 항목 | 내용 |
|------|------|
| 역할 | 윈도우 BalloonTip 시스템 알림 |
| 보안 | 스크립트와 데이터 분리: `$args[0]`, `$args[1]`, `$args[2]` 사용 |

---

### 3-10. `websync/db/history.py` — SQLite 이력 DB

| 항목 | 내용 |
|------|------|
| 역할 | 기기별(`device_ip`) 전송 완료 포스트 URL 이력 관리 |
| 동시성 | `threading.Lock()` + `sqlite3.connect(timeout=10.0)` |
| 테이블 | `synced_posts(url, device_ip PK, site_name, title, synced_at)` — 레거시 DB는 `device_ip='*'`로 자동 마이그레이션 |
| API | `needs_sync(url, target_ips)`, `mark_synced(..., device_ip)`, `is_synced_for_device()`, `remap_legacy_star_to_device(ip)` (파이프라인 시작 시 기본 기기로 자동 이관) |
| 레거시 `*` | 마이그레이션 시 `device_ip='*'` 부여. **전 기기 완료로 취급하지 않음**. 동기화 시작 시 첫 대상 IP로 이관 |

---

### 3-11. `websync/gui/` — GUI

| 항목 | 내용 |
|------|------|
| 프레임워크 | CustomTkinter (`customtkinter`) + tkinter 다이얼로그 |
| 조립 | `app_core/` (`SyncAppGui`), 탭 패키지: `sync_tab/`, `device_files/`, `settings_tab/` |
| 테마 | System/Light/Dark (`widgets.py` COLOR_* 튜플) |
| 탭 구조 | 뉴스 동기화 / Calibre / 이력 / 기기 파일 / 고급·서버 설정 |
| 비동기 | `threading.Thread(daemon=True)` + `root.after(0, callback)` 패턴 |
| 호환 | `gui/app.py`, `tab_sync.py` 등은 re-export 유지 |

---

## 4. 데이터 흐름 다이어그램

```
[사용자 / 윈도우 스케줄러]
           │
           ▼
   x3_websync.py (진입점)
     ┌─────┴──────┐
   GUI          --sync (백그라운드)
     │              │
     └──────┬────────┘
            │
            ▼
  SyncService.run_sync_pipeline()
            │
            ├─ ConfigManager.load_config()       ──► config.json
            │
            ├─ ScraperFactory.get_scraper(type)
            │     ├─ CssSelectorScraper          ──► 일반 웹 HTML
            │     ├─ RssScraper                  ──► RSS/Atom XML
            │     └─ NaverBlogScraper            ──► 네이버 RSS + PostView API
            │
            ├─ SyncHistoryDb.needs_sync(url, ips)──► sync_history.db (기기별 중복 제거)
            ├─ EpubBuilder.build()               ──► output/*.epub
            ├─ X3Uploader.upload_to_targets()    ──► http://{ip}/upload (미전송 기기만)
            ├─ SyncHistoryDb.mark_synced(..., device_ip)
            └─ ToastNotifier.show_toast()        ──► 크로스플랫폼 토스트 알림
```

---

## 5. 기능 확장 아이디어 (Feature Roadmap)

> **참고 (2026-07-31)**: 아래 HIGH/MEDIUM/LOW 항목의 대부분(로그 저장, 진행률, 이력 탭, 전용 스크래퍼, AI 요약, 표지, 번역, OPDS, 다중 기기, Watch, 웹 대시보드, frozen 경로·프로세스 락 등) 및 2026-07-31 감사 개선 사항(한글/비아스키 파일명 Short Hash 고유성, OPDS Windows 드라이브 대소문자 `normcase` 방어, 백업 `flush_backup_push` 종료 훅, 웹 대시보드 `mtime` 로그 정렬 등)이 **완료**되었습니다. 신규 작업 전 루트 `PROJECT_AUDIT.md`와 `docs/DEVELOPER.md`·코드 현황을 확인하세요. 아래 목록은 초기 로드맵 기록으로 유지합니다.

현재 아키텍처는 SOLID 원칙 기반으로 설계되어 있어 아래 기능들을 비교적 깔끔하게 추가할 수 있습니다.

---

### 🔴 HIGH — 핵심 UX 개선

#### A. 동기화 실행 로그 파일 저장
- **설명**: `logging` 모듈을 사용해 동기화 실행 기록을 날짜별 파일(`logs/sync_YYYY-MM-DD.log`)에 자동 저장
- **수정 모듈**: `x3_websync.py`, `service.py`
- **Why**: 스케줄러 백그라운드 구동 시 문제 발생 여부를 추후 확인 불가능 → 로그 파일 필수

#### B. 출력 폴더 바로 열기 버튼
- **설명**: GUI에 "출력 폴더 열기" 버튼 추가 → `subprocess.Popen(['explorer', output_dir])`
- **수정 모듈**: `gui.py`
- **Why**: 현재 생성된 EPUB을 확인하려면 탐색기를 직접 열어야 함

#### C. 수집 진행률 표시바 (ProgressBar)
- **설명**: 동기화 실행 중 각 사이트별 수집 상태를 `ttk.Progressbar`로 시각화
- **수정 모듈**: `gui.py`, `service.py` (콜백 시그니처 확장)

#### D. 동기화 이력 조회 탭
- **설명**: `sync_history.db`에 기록된 전송 이력을 GUI 내 테이블로 조회하고, 특정 항목을 삭제해 재전송 가능하도록 구현
- **수정 모듈**: `db_manager.py` (삭제 메서드 추가), `gui.py` (이력 탭 추가)

---

### 🟡 MEDIUM — 스크래퍼 확장

#### E. 티스토리(Tistory) 전용 스크래퍼
- **설명**: 티스토리 블로그 RSS는 본문 요약만 제공하는 경우가 많아 `CssSelectorScraper`로 커버 불가. 전용 스크래퍼로 본문 직접 접근
- **수정 모듈**: `scrapers.py` (`TistoryScraper` 추가, `ScraperFactory` 등록)
- **타입 이름**: `"tistory"`

#### F. 브런치(Brunch) 전용 스크래퍼
- **설명**: 카카오 브런치는 작가 기반 장문 콘텐츠가 많고 CSS 구조가 특수. 전용 스크래퍼로 본문, 썸네일 텍스트, 작가명 추출
- **수정 모듈**: `scrapers.py` (`BrunchScraper` 추가)
- **타입 이름**: `"brunch"`

#### G. YouTube 채널 자막 수집 스크래퍼
- **설명**: YouTube 동영상 한국어 자막(자동생성 또는 수동)을 `youtube_transcript_api`로 수집해 EPUB 변환
- **수정 모듈**: `scrapers.py` (`YoutubeScraper` 추가)
- **타입 이름**: `"youtube"`
- **의존성 추가**: `pip install youtube-transcript-api`

#### H. Substack 뉴스레터 스크래퍼
- **설명**: Substack의 RSS 피드는 전체 HTML 본문을 제공. 현재 RssScraper로 기본 작동하나, Substack 특유의 레이아웃 클렌징 전용 처리 추가
- **수정 모듈**: `scrapers.py` (`SubstackScraper` 추가 또는 RssScraper 고도화)

---

### 🟡 MEDIUM — 콘텐츠 처리 개선

#### I. 이미지 선택적 포함 옵션
- **설명**: 사이트별로 이미지 포함 여부를 GUI 옵션으로 선택 가능하게 개선. 현재는 전체 제거
- **수정 모듈**: `scrapers.py`, `config_manager.py` (스키마: `"include_images": true/false`), `gui.py`

#### J. AI 기사 요약 삽입
- **설명**: OpenAI API 또는 로컬 Ollama LLM을 사용해 각 기사의 요약문을 자동 생성 후 EPUB 챕터 첫 문단에 삽입
- **수정 모듈**: `service.py` (파이프라인에 요약 단계 삽입), 신규 `summarizer.py` 모듈
- **설정 키 추가**: `"openai_api_key"`, `"ollama_host"`

#### K. 전자책 표지(Cover) 자동 생성
- **설명**: 날짜와 사이트명이 표시된 간단한 표지 이미지를 동적으로 생성해 EPUB에 첨부
- **수정 모듈**: `builder.py`
- **의존성 추가**: `pip install Pillow`

#### L. 기사 번역 기능 (한국어 외 언어 소스)
- **설명**: 영어 등 외국어 기사 수집 시 `googletrans` 또는 DeepL API를 통해 자동 번역 후 한국어 EPUB으로 빌드
- **수정 모듈**: `service.py`, 신규 `translator.py`

---

### 🟢 LOW — 플랫폼·인프라 확장

#### M. OPDS 카탈로그 서버 내장
- **설명**: 생성된 EPUB 파일들을 OPDS 표준으로 제공하는 경량 HTTP 서버 내장 → X3 기기의 OPDS 클라이언트에서 직접 브라우징 다운로드 가능
- **수정 모듈**: 신규 `opds_server.py`, `gui.py` (서버 시작/중지 버튼)

#### N. 다중 X3 기기 동시 전송 지원
- **설명**: 현재 단일 기기 주소만 지원. 여러 기기 주소를 목록으로 관리하고 `ThreadPoolExecutor`로 동시 전송
- **수정 모듈**: `config_manager.py` (스키마: `"x3_devices": [...]`), `uploader.py`, `gui.py`

#### O. 크로스플랫폼 알림 및 스케줄러 (macOS/Linux)
- **설명**: ~~Windows 전용~~ → **구현 완료**: `notifier.py`는 Windows/macOS/Linux, `scheduler.py`는 schtasks/launchd/crontab 지원
- **수정 모듈**: `notifier.py`, `scheduler.py` (유지보수만)

#### P. Calibre 서재 자동 Watch 동기화
- **설명**: Calibre 서재 폴더를 `watchdog` 라이브러리로 감시. 새 책 추가 시 자동으로 X3 기기에 전송
- **수정 모듈**: `calibre.py`, `service.py`, 신규 `watcher.py`
- **의존성 추가**: `pip install watchdog`

#### Q. 웹 UI 대시보드
- **설명**: Tkinter GUI 외에 FastAPI 기반 웹 인터페이스 제공. 원격 브라우저에서 동기화 제어 및 로그 확인 가능
- **수정 모듈**: 신규 `web_api.py`

---

## 6. 새 스크래퍼 추가 방법 (개발 가이드)

`websync/scrapers/`에 새 스크래퍼를 추가할 때 **타입 상수 한곳**을 기준으로 맞춥니다.

```python
# 1. websync/scrapers/my_type.py — BaseScraper 상속
from websync.scrapers.base import BaseScraper, fetch_url, maybe_strip_images

class MyScraper(BaseScraper):
    def fetch_articles(self, site_config: dict) -> list:
        return [{"title": "제목", "content": "<p>본문HTML</p>", "url": "고유URL"}]

# 2. websync/scrapers/types.py — SCRAPER_TYPES 튜플에 "my_type" 추가
#    (SPECIALIZED_TYPES 는 css 제외 전용 타입 — GUI CSS 필드 비활성에 사용)

# 3. websync/scrapers/factory.py — import + _scrapers["my_type"] = MyScraper()

# 4. (선택) websync/scrapers/presets.py — 한국 추천 프리셋 항목

# 5. x3_websync.spec hiddenimports 에 websync.scrapers.my_type 추가

# 6. 픽스처 단위 테스트 + (선택) scripts/validate_korean_scrapers.py 샘플
#    GUI combobox / validator 는 SCRAPER_TYPES 를 import 하므로 별도 하드코딩 불필요
```

반환 형식 (모든 스크래퍼 공통):
```python
{
    "title": str,
    "content": str,   # HTML 문자열
    "url": str        # 중복 제거 키
}
```

사용자 문서: `docs/USER_GUIDE.md` · 개발 요약: `docs/DEVELOPER.md` · 빠른 시작: `README.md`

---

## 7. 설정 스키마 확장 가이드

새 기능에 설정 항목이 필요하면 `ConfigManager.DEFAULT_CONFIG`에 먼저 추가합니다:

```python
DEFAULT_CONFIG = {
    ...
    "new_feature_option": "default_value",  # 여기에 추가
    ...
}
```

`load_config()`의 결손 키 자동 보강 로직이 기존 사용자의 `config.json`에 새 키를 자동으로 추가해 하위 호환성을 보장합니다.

---

## 8. 의존성 목록 및 역할

| 라이브러리 | 용도 | 필수 여부 |
|-----------|------|---------|
| `requests` | HTTP 요청 (스크래핑, 기기 업로드) | 필수 |
| `beautifulsoup4` | HTML/XML 파싱 | 필수 |
| `lxml` | XML 파서 백엔드 (RSS) | 필수 |
| `ebooklib` | EPUB 파일 생성 | 필수 |
| `tkinter` | GUI (Python 표준 내장) | 필수 |
| `sqlite3` | 동기화 이력 DB (Python 표준 내장) | 필수 |
| `Calibre` | 도서 서재 연동 (외부 설치) | 선택 |
| `Pillow` | 표지 이미지 생성 | 선택 (`requirements-optional.txt`) |
| `youtube-transcript-api` | YouTube 자막 수집 | 선택 (`requirements-optional.txt`) |
| `watchdog` | Calibre 폴더 감시 | 선택 (`requirements-optional.txt`) |

---

## 9. 자주 마주치는 이슈와 해결책

| 증상 | 원인 | 해결책 |
|------|------|--------|
| 스케줄러 실행 후 동기화 안됨 | 작업 경로 유실 → config.json 못 읽음 | `websync/scheduler/manager.py`의 `cd /d` 경로 확인 |
| EXE에서 설정·이력이 사라짐 | (구버전) PROJECT_ROOT가 임시 폴더 | `paths.py` frozen → exe 디렉터리 확인; 최신 빌드 사용 |
| `동기화가 이미 실행 중` | GUI와 `--sync` 또는 이중 실행 | 정상 방어 — `process_lock` / pipeline lock 대기 후 재시도 |
| `database is locked` 오류 | 동시 동기화 실행 | `websync/db/history.py`의 `timeout=10.0` 및 Lock 확인 |
| 네이버 포스트 본문 없음 | `div.se-main-container` 미발견 | `#postViewArea` 폴백 확인, 네이버 HTML 구조 변경 여부 점검 |
| CrossPoint 기기 크래시 | 한글/공백 파일명 전송 | `websync/upload/uploader.py` 세니타이징 로직 확인 |
| EPUB 한글 깨짐 | 인코딩 문제 | `websync/epub/builder.py`의 UTF-8 메타 선언 확인 |
| pythonw 실행 후 아무 일도 없음 | stdout=None 크래시 | `x3_websync.py`의 `NullWriter` 확인 |
| 동시 기동 시 config.json 저장 충돌 | Race Condition | `websync/config/manager.py`의 config 경로별 `ProcessFileLock`과 revision 확인 |
| PyInstaller 빌드 후 import 오류 | hiddenimports 누락 | `x3_websync.spec`의 `websync.*` 서브패키지 목록 확인 |

---

## 10. Git 커밋 컨벤션

```
feat:      새 기능 추가
fix:       버그 수정
refactor:  코드 구조 변경 (기능 변화 없음)
security:  보안 취약점 수정
docs:      문서 수정
test:      테스트 추가/수정
chore:     빌드, 의존성, 설정 변경
```

예시:
```
feat(scrapers): Add TistoryScraper for Tistory blog support
security(notifier): Replace inline PowerShell string injection with args binding
fix(scheduler): Lock working directory using cmd /c cd /d before execution
feat(gui): Add sync history viewer tab with re-send capability
```
