# Project Audit

> 후속 개선: 이 문서는 감사 당시 기록입니다. 현재 수정 상태와 검증 결과는 [구현 기록](docs/AUDIT_IMPLEMENTATION.md)을 확인하세요.

> 감사일: 2026-10-13 (Asia/Seoul)
>
> 기준: `main`, commit `b43f72d9104669205be8096525afa4e4fa4a106a`
>
> 관점: 기능 구현, 런타임 안정성, 데이터 흐름 및 복구. 애플리케이션·테스트 코드는 수정하지 않았다.

## 1. Executive Summary

핵심 기능은 상당 부분 구현되어 있다. 전체/선택 동기화, 미리보기, 사이트별·일간 합본 EPUB, 기기별 이력, 공유 데이터 폴더, Calibre/Watch, 기기 파일 관리, OPDS, 웹 대시보드 및 서명 업데이트가 실제 실행 경로에 연결되어 있다. 파이프라인 프로세스 락, 설정 파일 원자 교체·revision 검사, SQLite 트랜잭션, 성공 기기에만 이력을 기록하는 처리는 유효한 보호 장치다.

**전체 평가: Needs Work. 전체 위험도: Medium이며, 특정 조건에서 설정 유실과 개발용 테스트의 사용자 이력 변경 위험은 High다.** 광범위한 핵심 기능 장애나 Critical 보안 결함은 확인하지 않았다. 문제가 없다는 보증은 아니며, 실기기·외부 서비스·다른 OS 검증 범위는 제한적이다.

| 먼저 주목할 문제 | 우선순위 / 신뢰도 | 확인된 결과 |
|---|---|---|
| ISSUE-001: 공유 백업 push의 오래된 사이트 목록 저장 | High / Confirmed | push 도중 저장한 사이트 B가 로컬과 공유 출력에서 사라지고 push는 성공을 반환 |
| ISSUE-004: 일부 테스트가 기본 사용자 이력 DB에 접근 | High / Confirmed | 동일 테스트 흐름을 임시 환경에서 실행하면 기존 `*` 이력이 테스트 기기 `127.0.0.1`로 이관 |
| ISSUE-002: googletrans 비동기 API와 동기 호출의 불일치 | Medium / Confirmed | 설치된 4.0.2에서 번역 대신 원문 반환 및 미대기 coroutine 경고 |
| ISSUE-003: 취소 상태가 다음 미리보기·선택 전송에 남음 | Medium / Confirmed | 정상 미리보기 1건 → 취소 요청 → 다음 미리보기 0건, 선택 전송은 빌드 없이 cancelled |

**데이터 손상/유실:** SQLite 파일 자체의 물리적 손상은 확인하지 않았다. ISSUE-001은 저장된 사이트 변경의 논리적 유실을 일으킨다. ISSUE-004는 사용자 이력의 기기 귀속을 바꾸거나 로컬 사이드카 이력을 병합할 수 있다. 첫 수정 영역은 백업 push의 read-modify-write 경계와 테스트의 저장 경로 격리다.

전체 테스트 결과는 **472 passed, 1 failed**였다. 실패한 대시보드 테스트를 단독 재실행해도 실패했으므로 전체 테스트가 정상이라고 평가할 수 없다.

## 2. Project Understanding

### 목적과 실행 방식

CrossPoint 펌웨어를 사용하는 XTEINK X3/X4의 데스크톱 동반 앱이다. 웹/RSS/블로그/뉴스레터/YouTube 콘텐츠를 수집하고 EPUB으로 만들어 Wi-Fi로 전송한다. SQLite 이력으로 중복을 줄이고 Calibre 서재 및 로컬 전자책도 전송한다.

문서 및 설정 근거는 `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/DEVELOPER.md`, `requirements*.txt`, `pytest.ini`, `pyrightconfig.json`, `x3_websync.spec`, `.github/workflows/test.yml`, `.github/workflows/release.yml`이다. 사용자 제공 Git 규칙은 main에서 작업하도록 정한다. 과거 로드맵 항목을 미구현 기능으로 간주하지 않았다.

| 실행/기능 | 실제 흐름 |
|---|---|
| CLI 전체 동기화 | `x3_websync.main(--sync)` → `SyncService.run_sync_pipeline` → thread/process lock → 공유 pull → `run_sync_pipeline_locked` → scraper → 이력 필터 → 번역/요약 → EPUB → HTTP upload → 성공 기기의 SQLite 이력 → 공유 push → bool/exit code |
| GUI 전체 동기화 | `_run_immediate_sync` → UI 설정 검증·저장 → 추적 워커 → 위 CLI와 같은 서비스 → `root.after` → 결과 상태·이력 새로고침 |
| 미리보기 | `open_preview_window` → `preview_articles` → 동일 파이프라인 락·공유 pull → 수집·이력 필터 → 기사 목록; 전송·전송 이력 기록 없음 |
| 선택 전송 | `_run_selected_sync_task` → `sync_selected_articles` → 락·pull → 사이트별 기사 묶기 → 선택적인 번역/요약 → 미전송 기기별 EPUB → upload → 성공 이력·push |
| EPUB만 만들기 | `_run_build_only_task` → `build_selected_epubs` → 설정·기사 그룹 → `EpubBuilder.build/build_digest` → 출력 파일; 전송·전송 이력·번역/요약 없음 |
| 기기 파일 관리 | GUI 선택/확인 → `X3DeviceClient` → 원격 경로 정규화 → `/api/files`, `/upload`, `/download`, `/delete`, `/rename`, `/move` 등 → UI 결과 |
| Calibre/Watch | `CalibreManager`의 제한시간 있는 subprocess → 경로 → uploader; Watch는 이벤트 debounce·크기 안정화 → persistent pending 목록 → 큐 워커·파이프라인 락 → upload |
| 웹 대시보드 | 인증 POST `/api/sync` → GUI의 `sync_cb` → `begin_sync_pipeline_async`가 락 선점 → 202/409; `/api/cancel` → `request_cancel` |
| 업데이트 | `UpdateService` → HTTPS manifest → Ed25519·버전·만료·크기 검증 → 스트리밍 SHA-256 검증 → helper → 원자 교체 → smoke 실패 시 rollback |

### 저장 방식과 공유 상태

- `config.json`: 설정 정본. 결손 키 보강, `portable_data`/`backup_sync` 호환, config 경로별 프로세스 락, revision CAS, 고유 임시 파일·fsync·replace 및 `.bak` 사용.
- `sync_history.db`: `(url, device_ip)` 복합 PK인 전송 이력과 삭제 tombstone. `device_ip`라는 컬럼에 안정 기기 ID/alias 관련 키도 저장한다. 연결 timeout 10초, 트랜잭션 commit/rollback/close, thread lock을 사용한다.
- `output/`: 사이트별 또는 일간 합본 EPUB. 같은 날짜의 기존 파일이 있으면 시간 suffix로 새 파일을 생성한다.
- 공유 폴더: `sites.json`, `synced_posts.json`, manifest 및 폴더 락. 사이트·이력·삭제 표식·기기 registry를 병합한다. 잘못된 공유 JSON은 거부하고, pull 실패 시 기사 전송을 중단한다.
- 실행 상태: `service.config`, builder/uploader 컴포넌트, `_cancel_event`, `_last_pipeline_result`, `_pipeline_thread`, GUI 워커 집합, 백업 timer 및 Watch queue.
- 개발 실행은 프로젝트 루트, frozen 실행은 EXE 폴더를 데이터 기준으로 사용한다. 설정 시크릿은 로컬 JSON에 저장되며 UI 마스킹은 저장 암호화를 의미하지 않는다.

### 외부 의존성

필수 Python 의존성은 requests, BeautifulSoup, lxml, ebooklib, customtkinter, cryptography이며 pytest가 필수 목록에 포함되어 있다. 선택 의존성은 Pillow, googletrans, youtube-transcript-api, watchdog이다. Calibre CLI, OS 스케줄러, CrossPoint HTTP API, 원격 콘텐츠 사이트, AI/번역 서비스 및 GitHub 업데이트 서비스가 외부 경계다. PyInstaller spec은 Pillow/googletrans/YouTube/Watch 의존성을 제외하며 README도 경량 EXE의 제한을 설명한다.

## 3. Audit Coverage & Limitations

### 구조 및 코드 확인 범위

**CodeGraph MCP를 실제 사용했다.** `.codegraph/`가 있는 저장소에서 entrypoint와 심볼·파일 이름으로 소스 및 caller/callee를 조회했다. 일반 코드 검색은 CodeGraph 결과의 생략 구간이나 호출 유무를 보충할 때 사용했다.

| 영역 | 확인한 주요 모듈/보호 장치 |
|---|---|
| 실행·상태·동시성 | `x3_websync.py`, `pipeline/service.py`, `core/process_lock.py`, GUI `app_core/sync_control.py`, `helpers.py` |
| 사용자 동기화 흐름 | `sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py`, GUI `sync_tab/preview.py`, `sites.py` |
| 설정·이력·백업 | `config/manager.py`, validator/secrets, `db/history.py`, `backup/service.py`, `local_import.py`, portable 설정 및 기기 키 관련 호출 경계 |
| 수집·내용 처리 | scraper base/session/timeout/retry/redirect/body limit, factory, RSS/CSS, YouTube API 호환, URL safety, translator/summarizer |
| EPUB·전송·파일 | builder, sanitizer, uploader, device client, remote path, GUI device files actions |
| 서버 | dashboard handler/http_server/service/session 호출, OPDS auth/path confinement/chunk transfer/수명 주기, HTML templates |
| OS·선택 기능·배포 | scheduler, Calibre wrapper, Watch 및 GUI 큐/pending 처리, update manifest/installer/service, PyInstaller/CI/release 설정 |
| 테스트 설계 | conftest, service/preview/selected/digest/translator, backup interleavings, HTTP lifecycle, hermetic guard 및 전체 실행 결과 |

CodeGraph로 직접 확인한 주요 연결은 다음과 같다.

- `main` → `run_sync_pipeline` → `_run_pipeline_body` → `maybe_backup_pull`/`_reload_config` → 실제 pipeline → `upload_to_targets`/`mark_synced_many` → `maybe_backup_push`.
- `schedule_backup_push`/수동 공유 동기화/파이프라인 → `BackupSyncService.push` → `_push_unlocked` → `_apply_site_merge` → `ConfigManager.update_config`.
- GUI 미리보기/선택 전송 → 서비스 wrapper → preview/selected 로직 → `_cancel_event` 조회. GUI caller에서 상태를 초기화하는지 추가로 확인했다.
- `_on_close` → 서버/Watch stop → `shutdown_pipeline` → `flush_backup_push` → GUI 워커 wait → root destroy.
- `SyncService.__init__` → 기본 `SyncHistoryDb` 및 local sidecar import; 전체 pipeline → legacy 이력 remap. 일부 테스트가 이 생산 코드 경로를 그대로 호출한다.

### 실제 실행한 검사

| 실행 | 결과 |
|---|---|
| `pytest -q` | **472 passed, 1 failed**, 87.66초. Windows, Python 3.15.0 |
| `python -m pytest tests/test_http_server_lifecycle.py::test_dashboard_sync_requires_auth_and_reports_states -q --tb=short -ra` | **1 failed**, 0.98초. 단독 실행은 callback count `2 != 1`로 실패 |
| 임시 config/SQLite/공유 폴더 백업 interleaving probe | 동시 사이트 저장 직후 `[A, B]` → push 후 `[A]`, `ok=True` 확인 |
| 설치된 googletrans introspection 및 네트워크 없는 번역 probe | 4.0.2, `translate`는 coroutine 함수. 원문 반환 및 `was never awaited` 경고 확인 |
| 임시 경로·fake scraper의 취소 후 재실행 probe | 미리보기 1 → 0, 취소 flag 유지, 선택 전송 False/cancelled, builder 호출 0 |
| 임시 기본 루트에 기존 `*` 이력을 넣은 테스트 흐름 probe | 기본 DB를 쓰는 service 테스트와 같은 실행으로 이력 키 `*` → `127.0.0.1` 변경 확인 |
| loopback dashboard POST probe; 실동기화 대신 counter callback, client 재시도 없음 | 본문 없는 POST 12건 중 10건 202/2건 연결 오류, JSON POST 12건 중 4건 202/8건 연결 오류; 각 경우 callback 12회 실행 |

**테스트 격리 관련 감사 자체의 한계:** 전체 pytest를 먼저 실행한 뒤, 일부 테스트가 기본 프로젝트 루트 DB를 여는 사실을 발견했다. 전체 테스트 실행 전 사용자 DB의 비교본/hash를 확보하지 않았으므로 이번 실행이 실제 사용자 이력 행을 바꾸었는지는 확정할 수 없다. ‘사용자 데이터에 전혀 접근하지 않았다’고 주장하지 않는다. 이후 문제 재현은 임시 경로 또는 별도의 loopback 서버와 fake callback만 사용했고, 실제 이력에 복구·수정 작업을 하지 않았다.

전체 실행의 대시보드 실패는 `POST /api/sync` 응답을 읽는 과정의 `ConnectionResetError(10054)`였다. 단독 실행의 중복 callback은 테스트 helper가 `requests.ConnectionError`에 POST를 재시도하는 흐름과 일치한다. 추가 probe에서는 본문 없는 요청도 실패했으므로 **미소비 JSON 본문만을 원인으로 확정할 수 없다.** Python/Windows/네트워크/서버 종료 동작을 분리하지 못한 상태이며, 이 현상을 특정 제품 코드의 확정 결함으로 High-Risk Issues에 추가하지 않았다.

### 확인하지 못한 환경과 분석 한계

- 실제 X3/X4 파일 API·덮어쓰기·전송 완료 의미, 기기에서의 EPUB 표시와 이미지 동작, 실제 Calibre 도서관은 검증하지 않았다.
- 실제 사이트의 최신 HTML/RSS, YouTube 자막 접근, AI·번역 서비스 응답, 클라우드 동기화 클라이언트 간 충돌 및 GitHub live update는 호출하지 않았다.
- macOS/Linux의 실제 launchd/crontab, OS 알림, 디스플레이가 있는 GUI 전체 조작, 새 frozen EXE 빌드/교체는 실행하지 않았다. 기존 테스트의 mock/contract 결과와 코드만 확인했다.
- 모든 전용 scraper를 개별 실사이트에서 검증하지 않았다. 전체 테스트 통과 수를 외부 서비스 정상성의 증거로 사용하지 않는다.
- CodeGraph는 구조 탐색과 최신 소스 제공에 사용했으나 결과 일부는 크기 제한으로 생략되었다. 중요한 생략 구간은 직접 보충했다. 정적 caller 매칭은 런타임 모든 경로의 증명이나 테스트 커버리지 측정이 아니다.
- 이번 감사에서 coverage 측정, 의존성 설치, production 전송, 스케줄 등록, 기기 파일 삭제, 업데이트 적용은 수행하지 않았다.

### 반증되어 이슈로 남기지 않은 항목

- 정상 재실행 시 같은 날짜 EPUB을 반드시 덮어쓴다는 가설: builder의 기존 파일 검사·시간 suffix가 있어 제외했다.
- OPDS의 단순 path traversal/Unicode HTTP header 실패 가설: basename/realpath/normcase 제한 및 RFC 5987 filename 처리로 반증했다.
- 인증 없는 dashboard API 실행 가설: Bearer 또는 session 검증을 확인했다. production sync callback은 동기 전체 작업 대신 락을 선점하는 async service를 호출한다.
- 서버가 idle 연결 때문에 항상 무한 대기한다는 가설: dashboard/OPDS handler의 2초 socket timeout을 확인해 제외했다. 전체 작업 deadline 부재와는 별개의 문제다.
- 일부 기기 실패를 전체 성공 이력으로 기록한다는 가설: 성공 결과만 수집·트랜잭션 저장하고 전체 성공과 부분 성공을 나눈다.
- 원자적 설정 쓰기나 SQLite rollback 자체가 빠졌다는 가설: 보호 장치를 확인했다. ISSUE-001은 그 보호 장치 바깥에서 만들어진 오래된 값의 저장 문제다.

## 4. High-Risk Issues

이 절에는 코드 흐름과 임시 재현으로 확인한 문제만 넣었다. 절 이름과 개별 우선순위는 별개이며 Medium도 실제 기능 결함이면 포함한다.

### [ISSUE-001] 백업 push가 도중에 저장된 사이트 변경을 오래된 목록으로 덮어쓴다

- **위치:** `websync/backup/service.py:377` `_push_unlocked`; 특히 `:378`, `:461–479`의 `_apply_site_merge`. 관련 `websync/config/manager.py:349` `update_config`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** push 시작에 읽은 `config`로 사이트 목록과 tombstone을 병합한 뒤, `update_config`의 최신 `cfg`에 그 외부 snapshot을 그대로 대입한다. push 진행 중 저장된 새로운 사이트·편집·삭제가 반영되지 않는다.
- **발생 조건:** 자동 export timer, 수동 공유 동기화 또는 동기화 후 push가 설정을 읽은 다음, 다른 GUI 동작/워커/프로세스가 사이트를 저장하고 push가 `_apply_site_merge`를 실행한다. 폴더 락 대기·DB export·클라우드 파일 재시도가 경합 시간을 늘릴 수 있다.
- **영향:** 정상 저장된 사이트 추가/변경이 로컬 설정에서 사라지고 오래된 목록이 공유 정본으로 게시된다. `ok=True`이므로 사용자는 성공으로 인식할 수 있다.
- **근거:** 임시 설정에 A를 두고 push의 공유 JSON 읽기 직후 독립 `ConfigManager`로 B를 추가했다. 저장 직후 `[A, B]`, push 결과 `True`, 최종 로컬 `[A]`였다. `sites_payload`도 오래된 `sites`로 구성된다.
- **반증 확인:** backup service의 thread lock과 공유 폴더 lock은 일반 GUI config writer를 잠그지 않는다. config의 process lock/update_config는 최종 쓰기를 원자적으로 만들지만 mutator 바깥의 snapshot을 최신화하지 않는다. GUI CAS는 앞서 완료된 편집을 이후 backup mutator가 덮어쓰는 것을 차단하지 못한다. busy UI도 모든 사이트 편집이나 timer를 막지 않는다.
- **호출/영향 범위:** CodeGraph의 `push` callers는 `SyncService.maybe_backup_push`, timer/flush 및 수동 sync 경로다. 사이트 GUI 저장은 별도 config 경로로 들어오므로 같은 목록에 영향을 준다. pull의 `_apply_sites`는 최신 `cfg['sites']`를 내부에서 다시 병합하며 push와 다르다.
- **권장 수정 방향:** 사이트/tombstone 병합을 `update_config` mutator 안에서 최신 cfg 기준으로 수행하고, 그 저장 결과로 공유 payload를 만든다. config snapshot을 읽은 뒤 발생한 revision 변경을 무시하지 않도록 저장·export의 일관성도 정한다.
- **필요한 회귀 테스트:** Event/barrier로 push의 최초 read와 config write 사이를 고정한다. 다른 writer가 B 추가/A 편집/A 삭제를 각각 수행한 뒤 로컬과 공유 JSON 모두 최신 변경을 보존하고 unrelated config field도 유지해야 한다. thread뿐 아니라 독립 ConfigManager/process 경로도 포함한다.

### [ISSUE-002] googletrans 4.x의 coroutine을 기다리지 않아 번역이 실행되지 않는다

- **위치:** `websync/pipeline/translator.py:39` `_get_gtrans`, `:71–77` `_do_translate`, `:49–69` `translate_html`; `requirements-optional.txt`의 `googletrans>=4.0.0`.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** `gt.translate(...)`의 반환값을 동기 결과로 가정하고 바로 `.text`를 읽는다. 설치된 googletrans 4.0.2의 실제 메서드는 coroutine 함수다.
- **발생 조건:** 소스 실행에서 optional 의존성을 설치하고 전역 번역을 켠 뒤 googletrans provider와 사이트 `translate_to`를 지정한다.
- **영향:** 사용 가능 판정은 True지만 본문 번역은 실행되지 않는다. 예외 wrapper가 원문을 반환해 EPUB과 전송은 원문으로 계속 진행하며 미대기 coroutine 경고가 생긴다.
- **근거:** `inspect.iscoroutinefunction(googletrans.Translator.translate) == True`, 설치 버전 4.0.2를 확인했다. `<p>This article should be translated.</p>`를 넣은 실제 adapter 호출은 원문을 반환했고 `coroutine 'Translator.translate' was never awaited` 경고가 발생했다. coroutine을 실행하지 않아 외부 번역 요청은 보내지 않았다.
- **반증 확인:** `translate_html`의 catch는 전체 파이프라인 crash를 막지만 번역을 완료하지 않는다. 상위 availability/caller도 await하지 않는다. LibreTranslate는 별도 동기 구현이며 이 결함의 대상이 아니다. PyInstaller 경량 EXE는 googletrans를 제외하므로 해당 EXE 전체 장애로 일반화하지 않는다.
- **호출/영향 범위:** CodeGraph에서 전체 동기화와 선택 동기화가 `is_available_for_site` → `translate_html`을 호출한다. 사이트별 EPUB과 일간 합본의 전처리에 영향이 있다. EPUB만 만들기는 번역을 생략한다.
- **권장 수정 방향:** 지원하는 googletrans 버전의 async 계약에 맞는 adapter와 client 수명 관리를 구현한다. 워커 thread/event loop 경계를 명시하고 `source='auto'` 등 입력 계약도 실제 라이브러리에 맞춘다. dependency 버전 범위와 adapter 계약을 함께 관리한다.
- **필요한 회귀 테스트:** 실제 async shape의 stub/AsyncMock으로 await 여부, 번역 결과, tag 보존, client close를 확인한다. installed optional adapter 계약 테스트는 네트워크를 mock하고 coroutine 경고가 없어야 한다. 오류 시 원문 fallback과 로그는 별도 검증한다.

### [ISSUE-003] 취소 후 미리보기·선택 전송이 이전 취소 상태를 그대로 사용한다

- **위치:** `websync/pipeline/service.py:82–105` cancel event, `websync/pipeline/preview.py:31–74`, `websync/pipeline/selected_sync.py:42–46` 및 취소 검사, `websync/pipeline/epub_only.py:51–54`, GUI `websync/gui/sync_tab/preview.py:34`, `:205`, `:224`.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 취소는 service에 지속되는 Event를 set한다. 전체 sync body만 `clear_cancel()`을 호출하며 다음 preview/selected/build-only 작업 시작에서는 이전 상태를 초기화하지 않는다.
- **발생 조건:** 같은 GUI/service 인스턴스에서 작업 취소를 누른 뒤 새 미리보기 또는 선택 전송을 시작한다. 미리보기를 부분 수집 후 취소하고 반환된 기사 중 일부를 선택 전송하는 흐름도 해당한다.
- **영향:** 새 미리보기가 scraper 호출 전에 중단되어 0건을 반환하고 GUI는 ‘기사 없음’으로 표시할 수 있다. 선택 전송은 빌드/전송 없이 cancelled를 반환한다. 사이트별 EPUB만 만들기도 같은 flag의 영향을 받는다. 전체 sync를 실행하거나 앱을 재시작하면 우회할 수 있다.
- **근거:** 임시 DB/config와 1건을 반환하는 fake scraper에서 preview는 처음 1건이었다. `request_cancel()` 후 다음 preview는 0건이었고 flag는 계속 True였다. 이어 선택 전송은 False, `status=cancelled`, builder 호출 0이었다.
- **반증 확인:** GUI `_start_pipeline_ui_task`와 preview caller, service wrappers, 락 획득 helper를 확인했다. 이 경로들에는 cancel reset이 없다. repository 검색으로 `clear_cancel` 호출은 전체 sync body에만 있음을 보충 확인했다. 기존 selected 취소 테스트는 작업 전 set된 event가 취소를 유도하는지만 검증해 다음 작업의 독립성을 보장하지 않는다.
- **호출/영향 범위:** 하단 취소 또는 dashboard cancel → `request_cancel` → GUI preview/selected/build-only → 각 기능의 `is_cancel_requested` 검사. 전체 sync는 자체 reset 때문에 다른 결과를 보인다.
- **권장 수정 방향:** 새 작업이 락을 확보하고 수락되는 시점에 그 작업의 cancel 상태를 초기화하거나 작업별 Event를 둔다. busy 요청이나 동시에 실행 중인 작업의 취소를 초기화하지 않도록 작업 수락과 reset의 순서를 설계한다.
- **필요한 회귀 테스트:** 동일 service에서 preview → 취소 → preview/selected/build-only 재시작이 정상 처리되어야 한다. 현재 실행의 취소는 즉시 유효해야 하고 거부된 새 요청이 기존 작업의 취소를 지우면 안 된다. 부분 preview 취소 후 선택 전송도 포함한다.

### [ISSUE-004] 일부 테스트가 실제 기본 이력 DB를 사용하고 기존 이력을 변경할 수 있다

- **위치:** `tests/test_service.py:26`, `:144` 등 직접 service 생성; `tests/test_selected_sync.py:13–34`; `tests/test_pipeline_digest.py:31–39`; `tests/conftest.py`; `websync/pipeline/service.py:26–39`; `websync/db/history.py:33–38`; `websync/pipeline/sync_pipeline.py:89–100`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** ConfigManager만 mock한 뒤 `SyncService(cm)`를 만들면 생성자 내부에서 기본 PROJECT_ROOT의 `sync_history.db`를 열고 초기화하며 local sidecar import도 실행한다. DB 메서드를 생성 이후 mock해도 이미 이루어진 접근을 되돌리지 못하고, mock하지 않은 legacy remap도 남는다.
- **발생 조건:** 사용자 이력/사이드카 파일이 있는 개발 체크아웃에서 일반 `pytest -q` 또는 해당 service 테스트를 실행한다. 기존 `device_ip='*'` 행이 있으면 테스트 기기 주소로 이관될 수 있다. local sidecar가 있으면 이력 병합 경로에도 진입한다.
- **영향:** 개발자가 테스트만 실행해도 사용자 데이터에 쓰기가 발생할 수 있다. 잘못된 기기 귀속은 이후 실제 기기에서 중복 전송 판단을 바꾸며, local 데이터에 따라 테스트 결과도 달라질 수 있다. **애플리케이션 정상 GUI 실행 자체의 별도 결함으로 주장하는 것이 아니라, 테스트 실행 시 발생하는 데이터 위험이다.**
- **근거:** 기본 PROJECT_ROOT를 임시 폴더로 바꾸고 사용자 기존 행에 해당하는 synthetic `*` 이력을 넣었다. ConfigManager mock과 `needs_sync=False`를 쓰는 service 테스트 흐름을 실행하자 실제 DB의 이력 키가 `127.0.0.1`로 바뀌었다. 전송은 수행하지 않았다. conftest의 autouse fixture는 UI 언어만 초기화한다.
- **반증 확인:** SQLite lock/transaction은 이 변경을 정상 commit하며, 테스트 데이터인지 사용자 데이터인지 구분하지 않는다. `test_hermetic_suite.py`의 정적 금지 패턴은 사실상 `dist` 문자열 패턴 중심이어서 생성자를 통한 간접 기본 경로 접근을 탐지하지 못한다. 다른 integration 테스트가 tmp_path를 쓴다고 해서 이 테스트들도 격리되는 것은 아니다.
- **호출/영향 범위:** CodeGraph에서 테스트 → `SyncService.__init__` → `SyncHistoryDb()`/`_import_local_sidecars_once`; pipeline → `remap_legacy_star_to_device`. repository DB, legacy import JSON, lock/log 경로가 경계다.
- **권장 수정 방향:** service를 만들기 전에 DB·sidecar root·process lock·logger/output 경로를 모두 임시 환경에 주입한다. 공통 fixture 또는 명시적 생성자 주입으로 사용자 저장소 접근을 차단한다. 별도 sandbox에서 real I/O integration 테스트를 유지하고, 테스트 실행 중 허용 루트 밖 write는 fail-fast로 탐지한다.
- **필요한 회귀 테스트:** 별도 subprocess의 sandbox repo root에 sentinel DB/config/sidecar를 놓고 테스트 저장 경로는 다른 tmp_path로 지정한다. 테스트 전후 sentinel 행·파일 bytes가 같아야 하며, 금지 경로 접근 가드가 의도적으로 잘못된 `SyncService(cm)` 생성에서 실패해야 한다. 생산 데이터로 회귀 테스트를 하지 않는다.

## 5. Potential Functional Gaps

이 절은 추가 기능이나 보완 계약을 구분한다. 외부 환경에서 재현하지 못한 사항을 현재 확정 버그로 표현하지 않는다.

| 구분 | 보완점과 현재 근거 | 확인/개선 방향 |
|---|---|---|
| Confirmed Gap | 이미지 포함 설정은 HTML의 img를 유지하지만 확인한 builder는 본문 이미지를 EPUB item으로 다운로드·패키징하지 않는다. 외부 URL 이미지의 offline 표시는 보장되지 않는다. | ‘HTML 이미지 유지’와 ‘offline 이미지 포함’ 계약을 정하고, offline 지원 시 image manifest·상대 URL·크기/timeout 한도를 검증 |
| Likely Gap | `_on_close`는 `shutdown_pipeline(timeout=5)`의 False 결과를 확인하지 않고 추가 제한 대기 후 root를 destroy한다. daemon worker가 남을 수 있으며 업로드 timeout은 이보다 길다. | 느린 upload/DB commit/backup 중 종료를 subprocess로 시험. 전송 완료와 이력 기록 사이 종료의 재실행 정책을 정할 필요 |
| Likely Gap | 일반 클라우드 클라이언트가 각 PC의 로컬 폴더를 복제하는 경우, `ProcessFileLock`만으로 서로 다른 PC의 전송·게시를 전역 직렬화할 수 있다는 보장은 없다. 같은 물리적 공유 파일시스템 테스트와 구별해야 한다. | 독립 로컬 복제본·지연/충돌 파일로 검증. 필요하면 conflict 병합, 서버 CAS/lease 또는 사용자 동시 실행 정책 명시 |
| Confirmed Gap | HTTP lifecycle 테스트 helper는 모든 ConnectionError에 POST를 재시도한다. 응답만 유실된 경우 이미 수락된 callback을 반복한다. 단독 실패에서 count 2를 관측했다. | readiness는 읽기 요청으로 확인. 수락 이후의 transport 실패를 사전 연결 실패와 구분하고 mutation assertion에서는 자동 재시도 금지 |
| 추정 | callback은 실행되었는데 loopback HTTP 응답을 읽지 못한 현상이 실제 Windows 사용자 환경에서도 동기화 결과 표시를 혼란스럽게 할 수 있다. 이번 환경에서 원인은 미분리 상태다. | 다른 Python 버전·client·Windows 환경 및 request/response 완료 시점으로 재현. 근거 확보 전 unread body나 thread 시작 race 하나로 단정하지 않음 |

## 6. Documentation Mismatches

| 설명 | 실제 구현/확인 | 수정 방향 |
|---|---|---|
| README의 googletrans 자동 번역 및 optional requirements의 4.0.2 호환 언급 | import/설치는 가능하지만 실제 adapter 호출은 ISSUE-002로 번역 실패 | 설치 호환성과 기능 호환성을 구분하고 async adapter 지원 버전 명시 |
| README가 웹 대시보드에서 cancel과 live streaming log를 설명 | `/api/cancel`은 구현되어 있지만 `websync/servers/templates/dashboard.html`에는 취소 UI가 없다. 자동 5초 갱신은 status만이며 log는 초기/수동 fetch다. | API 제공과 사용자 UI 제공을 구분. 실제 UI를 추가하거나 기능 설명 조정 |
| docs/DEVELOPER.md의 hermetic 규칙 및 Windows CI 단계의 ‘temp paths’ 설명 | 일부 unit/service 테스트는 기본 DB/sidecar를 간접 사용한다(ISSUE-004). 정적 guard는 이 호출을 막지 못한다. | 실제 격리 fixture와 runtime write guard 확보 후 문서·CI 설명 유지 |
| CLAUDE/AGENTS의 CrossPoint crash 방지용 파일명 설명과 사용자 제공 ASCII 안전 설명 | `uploader.py:46`은 `str.isalnum()`으로 한글 등 Unicode 문자도 유지한다. hash는 basename 충돌 완화이며 ASCII 변환이 아니다. | 지원 펌웨어의 Unicode filename 계약을 실기기로 확인하고 문서와 코드의 허용 범위를 맞춤. 이번 감사에서는 기기 crash를 확정하지 않음 |

일부 내부 문서의 단순 module 이름·옛 로드맵은 유지보수 기록으로 처리했다. 그 자체를 기능 결함으로 집계하지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 백업 push의 사이트/tombstone 병합을 최신 config transaction 내부로 이동하고 최종 저장 결과를 export한다. 추가·편집·삭제 interleaving 회귀를 먼저 정의한다.
2. **ISSUE-004:** 사용자 데이터가 있는 checkout에서 테스트가 기본 저장소에 쓰지 않도록 모든 service fixture를 생성 전 격리한다. 테스트 명령을 재검증할 때에도 별도 sandbox를 사용한다.
3. 데이터 보호 확인은 임시 sentinel로 수행한다. 이번 감사에서 실제 사용자 데이터를 임의 복구하거나 수정하지 않는다.

### Phase 2 — Stability

1. **ISSUE-002:** googletrans async adapter와 client 정리, optional 버전 계약을 수정하고 네트워크 없는 adapter 테스트를 추가한다.
2. **ISSUE-003:** 작업 수락 시점의 cancel lifecycle을 통일하고 cancel → 새 작업 사용자 여정을 검증한다.
3. 실패한 dashboard 테스트의 재시도 설계와 Windows connection reset 원인을 분리한다. body 없는 정상 UI 요청도 포함하고 실제 pipeline lock의 중복 실행 방어를 유지한다.
4. 느린 network/DB/backup 상황의 종료·재실행을 시험하고 shutdown 실패 시의 동작 및 이력 불확실 상태를 명시한다.
5. Windows/macOS/Linux의 실행·경로·scheduler 계약과 새 frozen artifact를 플랫폼별로 확인한다.

### Phase 3 — Structural

1. service의 DB/storage root/lock/sidecar import/logger 경계를 주입 가능하게 해 테스트의 실제 사용자 저장소 접근을 방지한다.
2. 작업 상태와 cancel을 작업별로 관리하여 GUI/CLI/dashboard가 같은 상태 계약을 사용하게 한다.
3. 일반 클라우드 복제본 동시성 및 offline image 지원은 별도 기능 계약으로 정의한다. 외부 환경 증거에 따라 구현 범위를 정한다.
4. 문서 기능 표와 실행 가능한 API·UI 계약 테스트를 연결한다.

이 계획은 권고이며 애플리케이션·테스트 구현 변경은 수행하지 않았다.

## 8. Test Recommendations

아래는 **제안**이며, 위 3절에 적은 실행 외에는 실행했다고 주장하지 않는다. 모든 I/O는 임시 폴더·synthetic 데이터·loopback fake server에서 수행해야 한다.

| 유형 / 대상 | 구체적인 입력·조건 | 기대 결과 |
|---|---|---|
| Concurrency / ISSUE-001 | push 최초 config read 후 barrier; 다른 writer가 사이트 B 추가 또는 A edit/delete | 완료된 변경이 최종 로컬·sites.json 모두에 유지. push 성공은 최신 snapshot 게시를 의미 |
| Integration / ISSUE-001 | include_history on/off, 원격 사이트도 동시에 변경, export 중 config revision 증가 | remote 변경 및 local 최신 변경을 규칙에 따라 병합; unrelated config 보존 |
| Regression / ISSUE-004 | sandbox 기본 root sentinel `*` 이력 및 sidecar; 테스트 DB는 별도 tmp_path | sentinel 행·bytes 불변. 허용 저장 경계 밖 DB open/write는 테스트 실패 |
| Unit / ISSUE-002 | async translate stub가 ‘번역문’을 반환, 여러 HTML text node와 auto source | await 실행, tags 보존, 번역문 포함, coroutine warning 없음, client 정리 |
| Integration / ISSUE-002 | 설치된 지원 googletrans 버전 + HTTP transport mock; timeout/예외 입력 | 실제 API 계약과 adapter 일치; 실패 fallback과 logger 명확, 외부 요청 없음 |
| Unit / ISSUE-003 | 동일 service에서 Event set 후 새 작업 수락; busy 요청도 경쟁 | 수락된 새 작업의 취소는 초기화. busy 요청은 실행 중 작업의 cancel을 지우지 않음 |
| End-to-End / ISSUE-003 | preview 첫 사이트 수집 후 cancel → 부분 결과 기사 선택 → send 또는 새 preview | 새 작업 정상 실행; 이전 작업은 남은 사이트/기기 업로드 생략 |
| Integration / 핵심 sync | 실제 SQLite/EPUB + loopback source/device; 기기 A 성공/B timeout | A의 기사만 이력 저장. 실패 상태 반환. 재실행 때 B에만 미전송 기사 전달 |
| Regression / digest | A/B 기기 이력이 서로 다름, per_site/daily_digest 각각 | 기기별 EPUB에 필요한 기사만 포함. 모든 성공/부분 실패/신규 없음 상태 정확 |
| Integration / backup 장애 | empty/truncated/schema-invalid JSON, locked folder, export 단계별 disk 오류 | pull 실패 전송 0, 잘못된 정본 덮어쓰기 0, 부분 export 결과 명시, 다음 정상 retry 수렴 |
| Concurrency / 프로세스 락 | 독립 GUI/CLI 역할 subprocess가 같은 pipeline lock을 동시에 획득 | 한 작업만 실행, 거부 요청은 이력/파일 변경 없음, crash 후 새 프로세스 재획득 |
| Integration / DB | legacy schema 및 star row, 동일 `(url,key)` batch, transaction 중 강제 예외 | migration/PK/dedup 정확. 실패 batch rollback. tombstone보다 새 resend만 유효 |
| Platform-specific / dashboard | Windows Python 3.15 및 별도 지원 버전; body 없음/JSON POST; 재시도 없음 | 202와 callback 정확히 1회, 401 callback 0, busy 409. 수락 후 응답 유실은 별도 기록 |
| Regression / 테스트 helper | callback 수락 후 response close/reset을 fake server로 주입 | mutation 자동 재실행 없음; 실패를 readiness 문제로 숨기지 않음 |
| End-to-End / 종료·재실행 | upload 완료 전/후·mark commit 전·공유 push 중 close; 워커 지연 10초 초과 | 종료 결과 명확, 원자 파일 유지, DB integrity 유지, 재실행 시 성공/불확실 이력 처리 규칙 충족 |
| Integration / 기기 파일 | Korean basename, traversal 이름, interrupted download, 기존 local 파일, remote rename/move 오류 | 허용 경로 밖 write 없음, download 실패 시 기존 파일 보존, 개별 실패 UI와 partial count 정확 |
| Integration / 콘텐츠 | UTF-8/다른 XML encoding RSS, malformed selector, 16MiB 초과, public→private redirect | 문자 유지, 명확한 오류, body 한도 및 redirect 방어. 임의 HTML script/event 제거 |
| End-to-End / offline EPUB | 이미지 포함 on, 상대·절대 img URL, network 없는 reader emulator/실기기 | 정의된 offline 이미지 계약과 실제 표시 일치; EPUB manifest와 XHTML 검증 |
| Platform-specific / scheduler·Calibre | 공백/한글/특수문자 경로, native scheduler adapter fake 및 별도 실제 OS sandbox | cwd·argv 정확, 잘못된 시간 거부, 사용자 cron 항목 보존, subprocess timeout 처리 |
| Integration / Watch | 복사 중 크기 변동, 다수 이벤트, 일부 기기 failure, 중단 후 restart | 안정화 후 queue 처리, failed pending 유지, restart retry; 큐·워커 종료 계약 검증 |
| Regression / updater·frozen | 잘못된 서명/hash/만료/크기, download cancel, smoke fail, staged path alias | 적용 전 거부, 임시 파일 정리, 이전 EXE rollback 및 결과 기록; 새 빌드 --smoke 정상 |
| Integration / cloud replica | PC별 다른 local folders에 JSON 전파를 지연시키고 동시 scrape/push | 충돌·중복 정책 검증; 단일 shared-directory lock 테스트와 구별 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Needs Work | 주요 기능이 실제 연결되어 있고 많은 contract 테스트가 통과하지만 번역·취소 후 재실행 결함 확인 |
| Runtime Stability | Needs Work | thread/process lock 및 GUI 예외 복구 존재. dashboard 테스트 실패가 반복되고 종료의 긴 작업 계약은 미검증 |
| Data Integrity | Needs Work | SQLite transaction/PK와 config atomic write는 적절하나 backup snapshot 변경 유실 및 테스트의 사용자 이력 변경 경로 확인 |
| Error Resilience | Acceptable | 공유 pull 실패 시 전송 중단, 부분 업로드 기록, DB 예외·network timeout·update rollback 보호. 일부 fallback은 기능 실패를 최종 성공과 함께 허용 |
| Cross-platform Robustness | Acceptable | OS별 구현과 경로 방어 존재. 직접 실행한 환경은 Windows Python 3.15뿐이며 macOS/Linux 및 frozen 실동작은 미검증 |
| Test Confidence | Needs Work | 472 pass에도 1 fail, 단독 재실행 fail. async adapter·연속 사용자 작업·config interleaving 누락 및 기본 DB 접근으로 격리 신뢰 부족 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001 — 백업 push의 최신 사이트 변경 보존:** 실제 설정 유실을 막는다.
2. **ISSUE-004 — 테스트 저장소 격리:** 수정 검증 자체가 사용자 이력을 바꾸지 않게 한다.
3. **ISSUE-002 — googletrans async API 지원:** 현재 지원 의존성에서 작동하지 않는 번역 기능을 복구한다.

그 다음은 **ISSUE-003 취소 후 재실행 복구**다. 이번 감사는 위 문제의 수정 또는 production 데이터 복구를 수행하지 않았으며 보고서 작성으로 종료한다.

## 10. Remediation Status (2026-10-13)

위 1~9절은 b43f72d 기준 감사 기록이며 원래 재현 결과를 보존한다. 후속 작업에서 ISSUE-001~004를 수정했고 종료·대시보드·오프라인 이미지·클라우드 복제본 복구·문서·CI도 보완했다.

전체 로컬 suite는 528 passed, 1 skipped였고 분기 포함 coverage는 55%였다. 실제 config/backup/history 파일의 hash는 개선 시작 전과 동일하다. 한국어 문구와 문서 인코딩에 대한 후속 회귀도 통과했다.

[구현·검증 기록](docs/AUDIT_IMPLEMENTATION.md)에 현재 상태와 외부 미검증 범위를 정리했다. 실제 reader/Calibre/cloud client, native GUI와 연결된 browser 검증은 별개다. 여러 PC의 동시 전송을 전역 exactly-once로 보장한다고 주장하지 않는다.

코드 commit 774ddcd의 [CI](https://github.com/twbeatles/xteink-crosspoint-websync/actions/runs/38354390596)는 12개 job 모두 성공했다. 3개 OS와 Python 3.10/3.15 계약, optional translation 및 frozen smoke를 포함한다.
