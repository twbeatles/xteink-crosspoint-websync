# Project Audit

## Remediation Follow-up — 2026-09-15

감사에서 제안한 항목을 같은 작업 트리에서 구현했다.

| 항목 | 상태 | 적용 |
|---|---|---|
| ISSUE-001 CAS 우회 저장 | **Resolved** | `ConfigManager.patch_fields` 추가. 테마·언어·자동업데이트·portable wizard가 디스크 최신본에 해당 필드만 패치한다. |
| ISSUE-002 GUI 종료 시 daemon 동기화 | **Resolved** | `SyncService.shutdown_pipeline`이 cancel 후 워커 join. GUI 즉시/프리뷰/선택 동기화 스레드를 등록하고 `_on_close`에서 최대 5초 대기한다. |
| frozen i18n 스모크 | **Resolved** | `--smoke`가 `t("gui.tabs.sync")` 카탈로그 적재를 검사한다. |
| 대시보드 cancel 테스트 | **Resolved** | 콜백 횟수 단언을 `>= 1`로 완화. |
| README 스크래퍼 표 | **Resolved** | `SCRAPER_TYPES` 13종을 표에 맞춤. |
| 공유 폴더 동시 기록 안내 | **Resolved** | USER_GUIDE에 PC 간 락 한계를 명시. |

회귀: `test_patch_fields_keeps_sites_written_by_other_writer`, `test_shutdown_pipeline_cancels_running_worker`.

감사일: 2026-09-15  
작업 트리: `feat/i18n-ko-en` (기준 커밋 `991259d`, 그 위에 미커밋 i18n 변경 포함)  
범위: 기능 구현·런타임 안정성·데이터 무결성. 스타일/네이밍/리팩터링 취향은 제외.

2026-09-06 감사에서 열었던 ISSUE-001~005(설정 동시 저장 락, 다운로드 원자 교체, 로그인 Content-Length, 감시 파일 대기 큐, 업데이터 실패 콜백)와 후속 보완(tombstone, DB context manager, 파이프라인 config 스냅샷, OPDS `normcase`, 종료 시 watch worker 대기 등)은 **현재 코드에서 열린 이슈로 재분류하지 않는다.** 이번 감사는 그 이후 트리(특히 i18n 도입과 CAS를 우회하는 저장 경로)를 기준으로 한다.

---

## 1. Executive Summary

Xteink X3 WebSync는 수집 → EPUB → 무선 전송 → 기기별 이력의 핵심 경로가 락·스냅샷·성공 기기만 `mark_synced`로 잘 막혀 있다. 격리 pytest **296 passed** (14.5s). 광범위한 DB 파괴, SQL 인젝션, 인증 우회, 경로 탈출은 확인하지 못했다. Critical 이슈 없음.

**전체 위험도: Acceptable.**

가장 중요한 문제:

1. **설정 revision CAS를 건너뛰는 GUI 저장 경로** — 스케줄러 `--sync`와 GUI가 동시에 켜져 있을 때 사이트 목록·공유 폴더 메타를 덮어쓸 수 있다.
2. **동기화 중 GUI 종료** — daemon 스레드를 기다리지 않아 전송이 중간에 끊긴다(이력은 성공 시에만 기록되므로 재시도는 되지만, 사용자에게 경고가 없다).
3. **i18n EXE 번들 미검증** — 소스/테스트는  gre지만 frozen `--smoke`로 locale JSON 적재를 이번 감사에서 확인하지 못했다.
4. **README 수집 유형 표가 구현보다 짧다** — `newneek`/`substack`/`soonsal`/`moneyletter` 등이 본문 표에 없다.
5. **GUI·실제 기기·클라우드 충돌은 테스트가 얇다.**

**데이터 손상/유실 가능성:** 이력 SQLite는 성공 업로드만 기록하므로 “보냈는데 이력만 남는” 방향의 유실은 막혀 있다. 반대로 **설정 JSON을 낡은 메모리로 통째 저장하면 사이트 목록이 되돌아갈 수 있다.** 공유 폴더 동시 기록은 병합·tombstone으로 완화되지만 OS 파일락은 PC 간에 동작하지 않는다.

**가장 먼저 고칠 영역:** `save_config`를 쓰는 테마/언어/자동업데이트/마법사 경로를 `_safe_save_config`와 같은 revision CAS로 통일.

---

## 2. Project Understanding

### 목적

Xteink X3(CrossPoint) e-ink 리더기에 뉴스·블로그·RSS 등을 EPUB으로 만들어 Wi-Fi 전송하는 데스크톱 도구. 기기별 SQLite 이력으로 증분 동기화. Calibre·OPDS·웹 대시보드·공유 폴더(OneDrive 등)·자체 업데이트를 부가로 제공한다.

`README.md`, `CLAUDE.md`, `docs/USER_GUIDE.md`, `docs/DEVELOPER.md`, `requirements.txt`, `x3_websync.spec`, `pytest.ini`를 확인했다. **루트 `AGENTS.md`는 없다.**

### 주요 entrypoint

`x3_websync.py` `main()`:

- `--smoke` → 핵심 모듈 import
- `--apply-update` → 헬퍼가 스테이징 EXE 교체/롤백
- `--check-update` → 서명 매니페스트 조회
- `--sync` → GUI 락 없이 `SyncService.run_sync_pipeline()` (스케줄러용)
- 기본 → GUI 단일 인스턴스 락 후 `SyncAppGui`

### 핵심 모듈

| 영역 | 위치 |
|------|------|
| 설정 | `websync/config/manager.py`, `validator.py` |
| 파이프라인 | `pipeline/service.py`, `sync_pipeline.py`, `preview.py`, `selected_sync.py` |
| 수집 | `scrapers/` + `ScraperFactory` (13 타입) |
| EPUB | `epub/builder.py` |
| 업로드 | `upload/uploader.py`, `device_client.py` |
| 이력 | `db/history.py` |
| 공유 폴더 | `backup/service.py` |
| GUI | `gui/app_core`, `sync_tab`, `settings_tab`, `device_files` |
| i18n | `i18n/` (`t()`, `ko.json`/`en.json`) |
| 서버 | `servers/opds.py`, `servers/dashboard/` |
| 업데이트 | `core/update_installer.py`, `update_service.py` |

### 데이터 저장

- `config.json` — 프로세스 파일락 + 고유 tmp + `fsync` + `os.replace`, `_config_revision` CAS (`expected_revision` 사용 시)
- `sync_history.db` — `synced_posts(url, device_ip PK)`, WAL, `timeout=10`, 스레드 락, context manager commit/rollback/close
- `output/`, `logs/`
- 공유 폴더: `sites.json` / `synced_posts.json` / tombstone (SQLite 파일을 클라우드에 두지 않음)

### 외부 의존성

필수: requests, bs4, lxml, ebooklib, customtkinter, cryptography.  
선택: Pillow, googletrans, youtube-transcript-api, watchdog.  
런타임 외부: CrossPoint HTTP, 웹 소스, Calibre CLI, OS 스케줄러, 클라우드 폴더 클라이언트.

### 핵심 실행 흐름

```
CLI main / GUI _run_immediate_sync
  → SyncService.run_sync_pipeline
  → 스레드 Lock + ProcessFileLock (비차단)
  → maybe_backup_pull → config 스냅샷
  → ScraperFactory.fetch_articles (http(s)만)
  → SyncHistoryDb.needs_sync (기기 키/alias)
  → 번역·요약(선택) → EpubBuilder
  → upload_to_targets(only_ips=pending)
  → 성공 IP만 mark_synced_many
  → toast / last_pipeline_result → backup push → 락 해제
```

선택 동기화·프리뷰는 동일 파이프라인 락을 공유한다. 웹 대시보드 즉시 동기화는 `begin_sync_pipeline_async`로 락을 HTTP 스레드에서 선점한 뒤 daemon 워커에서 본문을 실행한다.

---

## 3. Audit Coverage & Limitations

### 확인한 모듈

진입점, `SyncService`/`sync_pipeline`/`selected_sync`/`upload_results`, `ConfigManager` 저장·CAS, `BackupSyncService` merge/tombstone, `SyncHistoryDb`, `X3Uploader`/`DeviceClient`/`normalize_remote_path`, OPDS 인증·경로 `normcase`, 대시보드 인증, 스케줄러 argv, 업데이트 교체/롤백, GUI 종료·테마/언어 저장, i18n 카탈로그 로더.

### CodeGraph로 본 호출 관계

- `run_sync_pipeline` ← `x3_websync.main`, `gui/app_core/sync_control._run_immediate_sync` (테스트: `test_pipeline_digest`, `test_service`)
- `upload_to_targets` ← 파이프라인·선택동기화·직접업로드·Calibre·watch
- `mark_synced` / `mark_synced_many` ← 파이프라인만 실질 기록, 테스트 `test_db`/`test_backup_service`
- `save_config` / `update_config` ← GUI·backup·local_import. **일부 GUI 호출은 `expected_revision` 없음**
- `begin_sync_pipeline_async` ← 웹 대시보드 `sync_cb`
- DeviceClient 목록은 이름에 `/` `..` 를 걸러 내고, OPDS 다운로드는 `realpath`+`normcase`로 output_dir 밖으로 못 나간다

### 실행한 테스트

`python -m pytest -q` → **296 passed in 14.46s** (Windows, Python 3.14.7).  
실제 X3 기기, OneDrive 두 PC 동시 기록, PyInstaller frozen EXE, macOS/Linux 스케줄러는 실행하지 않았다.

### 확인하지 못한 것

- CrossPoint 펌웨어 `/upload` 부분 POST 중단 시 기기 측 파일 상태
- 클라우드 폴더의 실제 last-write-wins 타이밍
- frozen EXE에서 `websync/i18n/locales/*.json` 적재 (`x3_websync.spec` datas에는 추가됨)
- GUI를 사람이 조작하는 E2E

### 분석 한계

CodeGraph는 심볼·호출 그래프를 주지만 Tk `after`/daemon 스레드·`schtasks` 같은 프로세스 밖 효과는 정적이다. 동적 레이스는 코드 경로와 락 범위로 추론했고, 별도 재현 프로세스를 띄우지는 않았다.

---

## 4. High-Risk Issues

### [ISSUE-001] 테마·언어·자동업데이트 저장이 config revision CAS를 건너뛴다

* **위치:** `websync/gui/settings_tab/tab.py` `_on_app_theme_changed`, `_on_ui_language_changed`; `websync/gui/settings_tab/updater.py` `_save_updater_settings`; `websync/gui/portable_wizard.py` `_mark_wizard_done`
* **우선순위:** High
* **신뢰도:** Likely (저장 API가 디스크 revision을 읽지 않음은 Confirmed. 다중 프로세스 덮어쓰기는 코드 경로상 도달 가능하나 이번 감사에서 두 프로세스를 띄워 재현하지는 않음)
* **문제:** 대부분의 GUI 저장은 `_safe_save_config` → `save_config(..., expected_revision=...)` 로 충돌을 감지·병합한다. 위 경로만 `save_config(self.service.config)` 를 호출해 **메모리 스냅샷으로 파일을 통째 교체**한다. `except Exception: pass` 로 실패도 삼킨다(테마/언어/자동업데이트).
* **발생 조건:** GUI가 떠 있는 동안 스케줄러 `--sync` 또는 다른 프로세스가 backup pull/push로 `config.json` revision을 올린 뒤, 사용자가 화면 테마·표시 언어·시작 시 업데이트 확인을 바꾼다.
* **영향:** 디스크에만 있는 사이트 목록·portable 메타·다른 탭에서 저장한 값이 이전 GUI 메모리로 되돌아갈 수 있다. 이력 DB 자체는 건드리지 않지만 **구독 설정 유실**은 재수집/재전송 범위에 영향을 준다.
* **근거:** `ConfigManager.save_config`는 `expected_revision is not None` 일 때만 디스크 revision을 비교한다. 생략 시 락만 잡고 `_save_config_unlocked` 한다. `_safe_save_config` (`helpers.py:121`) 주석과 구현이 이 충돌을 명시적으로 다루는데, 테마/언어는 그 헬퍼를 쓰지 않는다.
* **반증 확인:** config 경로별 `ProcessFileLock`은 **쓰는 순간을 직렬화**할 뿐, 낡은 내용을 쓰는 것을 막지 않는다. 파이프라인은 시작 시 config를 deepcopy 하므로 실행 중 전송 대상은 보호된다. 문제는 파이프라인 **종료 후 디스크에 남은 최신 설정**을 GUI가 되돌리는 쪽이다. `update_config(mutator)` 경로(watch pending_files 등)는 RMW라 해당 없음.
* **호출/영향 범위:** 저장 → `config.json` 전체. 다음 `load_config`/`_reload_config`를 타는 GUI 사이트 트리, `--sync`, backup push 정본.
* **권장 수정 방향:** 해당 저장을 `_safe_save_config` 또는 `update_config`로 바꾸고, 테마/언어는 `appearance_mode`/`ui_language`만 mutator로 갱신. 실패 시 사용자에게 알린다.
* **필요한 회귀 테스트:** GUI 메모리 revision=N, 다른 프로세스가 sites를 바꾸고 revision=N+1로 저장한 뒤 테마 저장을 시뮬레이트 → 디스크 sites가 유지되고 appearance_mode만 갱신되는지.

### [ISSUE-002] GUI 종료가 진행 중 동기화 daemon을 기다리지 않는다

* **위치:** `websync/gui/app_core/sync_control.py` `_run_immediate_sync` (daemon `Thread`), `_on_close`; `websync/pipeline/service.py` `begin_sync_pipeline_async`
* **우선순위:** Medium
* **신뢰도:** Confirmed (종료 훅에 파이프라인 join/cancel 대기가 없음)
* **문제:** 즉시 동기화·대시보드 기동 모두 `daemon=True` 스레드다. `_on_close`는 `flush_backup_push`, OPDS/대시보드/watch 중지, watch worker 최대 3초 대기 후 `root.destroy()` 한다. 실행 중 파이프라인에 `request_cancel`도, join도 없다.
* **발생 조건:** 하단 “즉시 동기화” 또는 웹 대시보드 동기화 중에 창을 닫는다.
* **영향:** 워커가 프로세스와 함께 죽는다. `mark_synced`는 업로드 성공 후에만 호출되므로 **허위 완료 이력은 남지 않는다.** 기기로의 HTTP POST가 중간에 끊기면 해당 회차는 실패로 끝나고 다음 실행에서 재시도된다. `ProcessFileLock`은 OS가 핸들을 닫으면 풀린다(잔존 `.lock` 파일만으로는 다음 `msvcrt.locking`/`flock`을 막지 않음). 사용자에게는 경고 없이 작업이 사라진다.
* **근거:** `_on_close` 본문 (`sync_control.py:72-88`)과 `_run_immediate_sync`의 `daemon=True`.
* **반증 확인:** watch 정지는 이전 감사에서 추가됨. 파이프라인은 해당 없음. 이력 손상 방향은 `collect_mark_entries`가 실패 IP를 건너뛰어 완화됨.
* **호출/영향 범위:** GUI 즉시 동기화, 대시보드 `sync_cb` → `begin_sync_pipeline_async`. `--sync` CLI는 동기 실행이라 해당 없음.
* **권장 수정 방향:** 종료 시 `request_cancel` 후 짧은 join, 또는 “동기화 중입니다. 종료할까요?” 확인. daemon 대신 non-daemon + 타임아웃.
* **필요한 회귀 테스트:** 파이프라인 락을 잡은 채 `_on_close` 상당 훅이 cancel을 호출하는지; 업로드 mock 도중 종료해도 `mark_synced`가 호출되지 않는지.

---

## 5. Potential Functional Gaps

* **Likely Gap — frozen i18n 리소스:** `x3_websync.spec`에 `websync/i18n/locales/*.json` datas와 hiddenimports가 있다. 이번 감사는 소스에서 `t()`·카탈로그 패리티 테스트만 확인했다. EXE에서 카탈로그를 못 읽으면 UI가 키 문자열(`gui.tabs.sync`)로 떨어진다 (`load_catalog` 실패 시 빈 dict). frozen `--smoke`에 카탈로그 로드를 넣는 편이 안전하다.
* **Likely Gap — 종료 확인 UI:** ISSUE-002와 연결. 기능 버그라기보다 운영 안정성 공백.
* **Likely Gap — 두 PC가 같은 공유 폴더에 동시에 push:** 폴더 락은 로컬 `ProcessFileLock`이라 머신 간에 상호 배타가 아니다. pull/push가 remote를 먼저 병합하고 tombstone을 쓰므로 **다음 동기화에서 합쳐질 가능성은 있다.** 한쪽 write가 OneDrive last-write-wins로 잠시 안 보이는 창은 남는다. 현재 설계의 한계로 보고 Critical로 올리지 않는다.
* **Confirmed Gap — README 수집 유형 표:** 구현 `SCRAPER_TYPES`는 css/rss/velog/naver/tistory/brunch/newneek/youtube/substack/naver_cafe/naver_post/soonsal/moneyletter. README 표는 이 중 일부만 나열한다. 동작 버그는 아니다.
* **추정 — `include_images`:** USER_GUIDE에 원격 URL 유지·EPUB 미내장이라고 명시됨. 오프라인 이미지 기대를 버그로 보지 않는다.
* **추정 — 언어 변경 후 재시작:** 설정 안내와 일치. CTkTabview 탭명 재생성 비용 때문에 의도된 제약.
* **추정 — GUI 자동화 테스트 공백:** CustomTkinter 탭은 단위 테스트가 거의 없고 i18n 가드(AST 한글 리터럴)로 회귀를 보완한다.

단순 enhancement(라이브 언어 전환, 이미지 임베드)는 버그로 적지 않았다.

---

## 6. Documentation Mismatches

| 문서 | 실제 | 비고 |
|------|------|------|
| `AGENTS.md` | 파일 없음 | 감사 지침의 AGENTS 확인 항목은 충족 불가 |
| `README.md` 콘텐츠 소스 표 | 13종 스크래퍼 중 일부만 표에 있음 | `newneek`, `substack`, `soonsal`, `moneyletter`, `naver_post` 누락 |
| `CLAUDE.md` 스크래퍼 13종 | `types.py`와 일치 | 문제 없음 |
| USER_GUIDE 이미지 포함 | 코드가 img를 EPUB에 다운받지 않음 | 문서가 제한을 이미 설명 |
| USER_GUIDE/README 표시 언어 | `ui_language` auto/ko/en 구현과 일치 (미커밋 i18n) | 문서가 코드보다 앞서 있지 않음 |
| 2026-09-06 `PROJECT_AUDIT.md` 테스트 수 283 | 현재 296 | 이 파일이 갱신됨 |

설정 프로세스 락, 기기 alias, YouTube RSS URL, 경량 EXE 선택 의존성은 이전 감사 이후 문서와 코드가 맞춰져 있다.

---

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. 테마·언어·`auto_check_update`·portable wizard 저장을 `update_config` 또는 `_safe_save_config`로 통일 (ISSUE-001).
2. 저장 실패를 `except: pass`로 숨기지 말 것.

### Phase 2 — Stability

1. GUI 종료 시 파이프라인 cancel + 제한 대기 또는 확인 대화상자 (ISSUE-002).
2. frozen `--smoke`에서 `load_catalog("ko")` 키 존재 검증.
3. 웹 대시보드 `/api/cancel` 테스트가 POST 재시도로 콜백이 2회여도 깨지지 않게 하거나, 테스트 헬퍼가 성공한 POST를 재시도하지 않게 조정.

### Phase 3 — Structural

1. GUI 설정 저장 진입점을 한 헬퍼로만 노출해 CAS 우회를 컴파일/린트 수준에서 막기.
2. README 스크래퍼 표를 `SCRAPER_TYPES`와 동기화.
3. 공유 폴더 동시 기록 한계를 USER_GUIDE에 한 문단으로 명시.

실제 코드는 이 감사에서 수정하지 않았다.

---

## 8. Test Recommendations

### ISSUE-001 (Unit/Concurrency)

- **입력:** 임시 `config.json` revision=1, sites=[A]. 프로세스 A가 sites=[A,B], revision=2로 저장. 프로세스 B(GUI 흉내)는 메모리 revision=1, sites=[A], `appearance_mode="Dark"` 만 바꿔 `save_config` (현재 구현) 호출.
- **현재 기대(버그):** 디스크 sites가 [A]로 후퇴할 수 있음.
- **수정 후 기대:** sites=[A,B] 유지, `appearance_mode=Dark`, revision=3.
- `_safe_save_config`/`update_config` 경로로 같은 시나리오를 통과시키는 회귀를 `tests/test_config_manager.py`에 추가.

### ISSUE-002 (Unit)

- **입력:** `SyncService._try_acquire_pipeline_locks` 성공 상태에서 close 훅 호출.
- **기대:** `request_cancel`이 호출되거나, 문서화된 확인 없이 destroy하지 않음. `mark_synced_many`는 업로드 mock이 끝나기 전에 호출되지 않음.

### i18n frozen (Integration)

- **입력:** PyInstaller 산출물 또는 `sys.frozen` + `_MEIPASS` 픽스처에서 `load_catalog("ko")`.
- **기대:** `gui.tabs.sync` 등 필수 키가 비어 있지 않음. `--smoke` 종료 코드 0.

### 핵심 사용자 흐름 (이미 있는 것 유지)

- **Unit:** `needs_sync` / `pending_device_ips` / `collect_mark_entries` — 한 기기 실패 시 성공 기기만 이력.
- **Integration:** `test_pipeline_digest.py` — 부분 성공은 overall False.
- **Concurrency:** 기존 두 프로세스 config 저장 테스트 유지.
- **Platform:** `test_scheduler.py` Windows 경로 공백·Linux CI; `test_opds_normcase.py`.
- **Regression:** i18n `test_i18n_catalogs.py` (ko/en 키 동일), `test_i18n_no_hangul_literals.py`.
- **End-to-End (미보유):** 실기기 1대에 사이트 1개 limit=1 전송 후 이력 행과 기기 파일 존재. 이번 감사에서는 실행하지 않음.

### 대시보드 (Regression)

- `/api/cancel` 인증 실패는 콜백 0회, 인증 성공은 **1회 이상** (테스트 헬퍼가 POST를 재시도할 수 있음). 본문 `ok: true`.

---

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|------|------|------|
| Functional Correctness | **Good** | 수집·중복 제거·부분 재전송·취소 경계가 코드와 테스트로 일관됨 |
| Runtime Stability | **Acceptable** | 락·스냅샷·서버 stop은 갖춤. GUI 종료 vs daemon 동기화가 약함 |
| Data Integrity | **Acceptable** | DB는 성공 기기만 기록. 설정 CAS 우회가 사이트 JSON을 되돌릴 수 있음 |
| Error Resilience | **Acceptable** | 사이트 단위 예외는 파이프라인을 계속. 일부 GUI 저장은 예외를 삼킴 |
| Cross-platform Robustness | **Acceptable** | 스케줄러/경로/OPDS normcase 테스트 있음. 이번 실행은 Windows만 |
| Test Confidence | **Acceptable** | 296 통과, 핵심 파이프라인·설정·이력은 커버. GUI·실기기·frozen i18n은 얇음 |

**실제로 먼저 수정할 문제 3개**

1. 테마/언어/자동업데이트/마법사의 `save_config` CAS 우회 (ISSUE-001)
2. GUI 종료 시 진행 중 동기화 처리 (ISSUE-002)
3. frozen 빌드에서 i18n 카탈로그 로드를 `--smoke`로 고정

---

*CodeGraph: `run_sync_pipeline`, `upload_to_targets`, `mark_synced_many`, `save_config`, `BackupSyncService.pull/push`, `DeviceClient.list_files`, `DashboardHandler._is_authenticated`, `apply_staged_update`, `is_allowed_fetch_url`, `_safe_save_config`, `ProcessFileLock`.*  
*테스트: `python -m pytest -q` → 296 passed (2026-09-15, 이 작업 트리).*
