# Project Audit

감사일: 2026-09-06 (Asia/Seoul)

대상 커밋: `bc4071ec0ff0d53febbea9a0cf02e75762782a7d` (`main`)

범위: 기능 구현, 런타임 안정성, 데이터 무결성. 아래 감사 결과는 기준 커밋에서 확인한 문제를 기록하며, 이어진 개선 작업의 결과는 바로 아래 후속 상태에 반영했다.

## Remediation Follow-up — 2026-09-06

감사에서 확인한 5개 이슈와 구체적으로 제안한 안정성 보완 작업을 구현했다. 이 절의 상태가 아래 원래 감사 시점의 평가보다 우선한다.

| 감사 항목 | 상태 | 적용 결과 |
|---|---|---|
| ISSUE-001 설정 동시 저장 | **Resolved** | config 경로별 프로세스 락과 고유 임시 파일을 적용하고, load/save/update 및 revision 검사를 동일 임계 구역에서 처리한다. 실제 두 프로세스 회귀 테스트를 추가했다. |
| ISSUE-002 다운로드 원본 훼손 | **Resolved** | 숨김 임시 파일로 스트리밍한 뒤 `fsync`와 원자적 교체를 수행한다. 실패 시 기존 파일과 무관한 부분 파일을 보존하지 않는다. |
| ISSUE-003 로그인 응답 길이 | **Resolved** | UTF-8 byte body를 먼저 만들고 그 길이를 전송한다. 전체 body와 세션 cookie를 읽는 HTTP 회귀 테스트를 추가했다. |
| ISSUE-004 감시 파일 유실 | **Resolved** | 불안정 파일을 제한적으로 재검사하고 수정 이벤트도 처리한다. 업로드 대기 목록을 config에 저장하여 실패·재시작 후 다시 처리한다. |
| ISSUE-005 업데이터 실패 UI | **Resolved** | 예외 메시지를 callback 생성 전에 값으로 고정했다. worker 종료 뒤 callback을 실행하는 실패 회귀 테스트를 추가했다. |
| 공유 삭제 전파 | **Resolved** | 사이트와 동기화 이력에 timestamp tombstone을 추가하고 pull/push 및 수동 import/export에 적용했다. 오래된 원격 항목이 삭제를 되돌리지 못한다. |
| DB 연결 수명 | **Resolved** | 모든 SQLite 작업에 commit/rollback/close를 보장하는 context manager를 적용했다. |
| 업데이트 메모리 사용 | **Resolved** | 다운로드 청크를 리스트에 누적하지 않고 staging 검증기로 직접 스트리밍한다. |
| 실행 중 설정 변경 | **Resolved** | 전체·선택 동기화 시작 시 config와 uploader/builder/DB 참조를 snapshot으로 고정한다. |
| 단일 기기 이력 의미 | **Resolved** | 안정 ID 또는 사용자가 지정한 alias만 동일 기기로 취급하고 URL 전체에 대한 전역 fallback을 제거했다. |
| 서버·종료 복구 | **Resolved** | dashboard/OPDS socket과 handler thread를 명시적으로 닫고, GUI 종료 시 감시 worker를 제한 시간 동안 기다린다. |
| 문서 불일치 | **Resolved** | YouTube RSS URL, 경량 EXE 선택 기능, 공유 충돌·삭제 의미, config 프로세스 락, 기기 alias 정책을 실제 구현에 맞췄다. |

이미지 포함 옵션은 원격 이미지 URL을 EPUB 내부 파일로 내려받는 기능이 아니다. 이 제한을 사용자 문서에 명시하며, 실제 기기에서 완전한 오프라인 이미지가 필요하다는 요구가 확인되기 전에는 버그로 분류하지 않는다.

후속 검증 결과는 `py -3.14 -m pytest -q` **283 passed**, `py -3.14 -m compileall -q websync x3_websync.py` 성공, `pyright` **0 errors**다. Pyright에는 현재 분석 환경과 선택 의존성의 interpreter 차이로 인한 unresolved-import warning 83개가 남았으나 새 type error는 없다. Windows의 로컬 loopback은 반복 테스트에서 간헐적인 TCP reset을 보였으므로 HTTP 통합 테스트는 각 요청을 새 연결로 보내고 transport reset만 제한적으로 재시도한다. 응답 status/body와 callback 호출 횟수 검증은 그대로 유지한다.

Windows 11, Python 3.14.7, PyInstaller 6.22.2에서 `pyinstaller --clean --noconfirm x3_websync.spec` 빌드가 성공했고, 생성된 `dist/x3_websync.exe`의 frozen `--smoke` 검사는 종료 코드 0을 반환했다. 산출물 크기는 26,780,241 bytes, SHA-256은 `10C30A4EE634BE2BBF6338A92E9C1F2EACAFD3722B62DFDA0B1AB75B85DEA27C`다. 공식 GitHub Actions 릴리스 환경은 Python 3.12이므로 태그 릴리스 시 CI 빌드가 최종 배포 산출물이다.

## 1. Executive Summary

프로젝트는 뉴스 수집·EPUB 생성·다중 기기 전송·이력 관리의 기본 구조와 방어 장치를 갖추고 있다. 격리 통합 검증에서 일부 기기 업로드 실패 후 해당 기기만 재시도하고, 완료된 기사는 다시 전송하지 않는 흐름이 정상 동작했다. 감사에서 확인한 파일 저장·설정 원자성, 웹 로그인, 비동기 실패 복구 문제는 후속 개선에서 수정됐다.

**현재 전체 위험도: Acceptable.** 기준 커밋에는 High 데이터 무결성 위험이 있었으나 회귀 테스트와 함께 제거했다. 광범위한 DB 파괴나 인증 우회는 확인하지 않았으며 Critical 이슈는 없었다. 실제 X3·클라우드 복제 충돌·Windows 외 OS는 추가 운영 검증 범위다.

| 이슈 | 우선순위 | 신뢰도 | 핵심 영향 |
|---|---|---|---|
| ISSUE-001 동시 설정 저장의 변경 유실 | High | Confirmed → Resolved | 프로세스 락·고유 임시 파일·다중 프로세스 테스트 적용 |
| ISSUE-002 다운로드가 기존 파일을 먼저 덮어씀 | High | Confirmed → Resolved | 임시 파일 완료 후 원자 교체, 실패 시 기존 파일 보존 |
| ISSUE-003 웹 로그인 응답 길이 오류 | High | Confirmed → Resolved | 실제 UTF-8 body 길이와 전체 응답 검증 적용 |
| ISSUE-004 성장 중인 감시 파일의 작업 유실 | Medium | Confirmed → Resolved | 안정화 재검사와 재시작 가능한 대기 큐 적용 |
| ISSUE-005 업데이터 실패 콜백의 예외 변수 소멸 | Medium | Confirmed → Resolved | 예외 문자열 값 캡처와 지연 callback 테스트 적용 |

**감사 시점의 데이터 손상·유실 가능성은 후속 수정으로 차단했다.** 설정 변경 유실과 PC 다운로드 파일 부분 덮어쓰기의 재현 테스트가 이제 원본·양쪽 설정 변경 보존을 확인한다. 실제 사용자 파일이나 production DB는 변경하지 않았다.

## 2. Project Understanding

### 목적과 실행 방식

Xteink X3의 CrossPoint 펌웨어 HTTP 인터페이스를 이용하여 웹 콘텐츠를 EPUB으로 만들고 Wi-Fi로 보내는 Python 데스크톱 도구다. GUI는 CustomTkinter/Tkinter이며 `x3_websync.py`가 GUI, `--sync`, `--smoke`, `--check-update`, 업데이트 헬퍼를 분기한다. Windows EXE는 PyInstaller로 만든다.

`README.md`, `CLAUDE.md`, `docs/DEVELOPER.md`, 의존성·pytest·Pyright·PyInstaller 설정과 CI/release 워크플로를 확인했다. 루트에 실제 `AGENTS.md` 파일은 없었다. 대화로 제공된 AGENTS 지침의 CodeGraph 우선 및 기본 main 작업 규칙을 적용했다. 별도 브랜치나 PR은 만들지 않았다.

### 핵심 모듈과 저장소

| 영역 | 구현 및 역할 |
|---|---|
| 진입점·락 | `x3_websync.py`, `core/process_lock.py`: GUI 단일 인스턴스, 파이프라인 스레드·프로세스 락 |
| 설정 | `config/manager.py`, `validator.py`: 기본값 병합, revision 검사, JSON 임시 저장·replace, 손상 JSON 보존 |
| 오케스트레이션 | `pipeline/service.py`, `sync_pipeline.py`, `preview.py`, `selected_sync.py` |
| 수집 | `scrapers/factory.py`의 등록 인스턴스와 RSS/CSS/사이트별 수집기, 공통 HTTP 세션 |
| 콘텐츠 | `epub/builder.py`, CSS/표지/HTML 정제, `pipeline/summarizer.py`, `translator.py` |
| 기기 I/O | `upload/uploader.py`, `device_client.py`, 주소·경로·기기 이력 키 유틸 |
| 이력 | `db/history.py`: 로컬 SQLite `synced_posts`와 `deleted_posts`, URL+device key 복합 키, 배치 기록·삭제 tombstone·기존 스키마 이관 |
| PC 간 공유 | `backup/service.py`, `format.py`, `atomic_io.py`: 공유 폴더의 sites/history JSON과 로컬 설정·DB 병합 |
| 부가 기능 | Calibre subprocess, watchdog 감시, OS 스케줄러, OPDS·웹 대시보드 |
| 업데이트 | 서명 매니페스트 검증 → 다운로드 → 해시·크기 검증 → 별도 헬퍼의 교체 및 smoke 실패 시 롤백 |

로컬 데이터는 `config.json`, `sync_history.db`, `output/`, `logs/`다. 공유 기능은 SQLite 파일 자체를 클라우드에서 공동 편집하는 방식이 아니라 `sites.json`, `synced_posts.json`, `manifest.json`을 병합하는 방식이다. 이력의 `device_ip` 컬럼에는 안정 기기 ID 기반 키도 저장된다. 설정에는 API 비밀값이 로컬 JSON으로 저장되며 GUI 마스킹과 gitignore가 있다.

필수 의존성은 requests, BeautifulSoup, lxml, ebooklib, customtkinter, cryptography 등이다. 선택 의존성은 Pillow, googletrans, youtube-transcript-api, watchdog이다. 외부 환경은 CrossPoint 기기, 웹사이트, Calibre, 선택적 요약·번역 API, OS 스케줄러와 클라우드 폴더 동기화 클라이언트다.

### 핵심 실행 흐름

- 전체 뉴스: `CLI main / GUI _run_immediate_sync → SyncService.run_sync_pipeline → 스레드·프로세스 락 → backup pull → 설정 reload → ScraperFactory → HTTP 수집·URL 키 생성 → DB.needs_sync → 번역·요약 → EpubBuilder → upload_to_targets → 성공 기기만 mark_synced_many → 상태·알림 → backup push → 락 해제`.
- 선택 뉴스: `open_preview_window → preview_articles → 동일 락·pull·수집·DB 필터 → 선택 목록 → sync_selected_articles → 설정 reload·후처리 → EPUB·업로드·이력`. 프리뷰 자체는 업로드하지 않는다.
- 웹: `로그인 화면 → POST /api/login → 토큰 검증·세션 쿠키 → /dashboard → POST /api/sync → begin_sync_pipeline_async → 위 뉴스 흐름`. 실행 락을 선점하여 수락/충돌을 구분한다.
- 파일 관리: `기기 파일 탭 → X3DeviceClient → 경로 정규화 → 목록/삭제/이름 변경/이동/다운로드 API → 임시 파일 fsync·원자 교체 → 결과 UI`.
- Calibre/감시: `calibredb 조회 → 실제 책 경로 → 업로더`; `파일 생성·이동 이벤트 → debounce·크기 안정성 확인 → 큐 → 파이프라인 락 → 업로드`.
- 설정 공유: `GUI 변경·타이머 / 시작·뉴스 동기화 → BackupSyncService → 폴더 파일 락 → timestamp+tombstone 병합 → 로컬 설정/DB 및 공유 JSON 기록`.

공유 가변 상태는 `service.config`, 교체 가능한 `service.uploader`·`epub_builder`, 실행 결과, 취소 이벤트, 백업 타이머 및 scraper의 최근 수집 통계다. 파이프라인 실행끼리는 직렬화하며 각 실행은 시작 시 필요한 설정과 서비스 참조를 snapshot으로 보관한다. config 저장은 별도의 경로별 프로세스 락으로 직렬화한다.

## 3. Audit Coverage & Limitations

### 구조 분석 범위

`.codegraph/`가 존재하여 **CodeGraph MCP `codegraph_explore`를 실제 사용**했다. 진입점→SyncService, 전체/선택/프리뷰→이력·업로드, 백업→설정·DB, GUI→웹·감시·업데이터를 우선 조회했다. 예를 들어 CodeGraph는 `run_sync_pipeline`의 GUI/CLI caller, `mark_synced_many`의 전체·선택 파이프라인 caller, `import_posts_union`의 백업·사이드카·이력 UI caller, `launch_update_and_exit`의 GUI caller를 반환했다.

상세 확인 범위는 설정 저장·병합, SQLite 배치 기록·이관, 뉴스 성공/부분 실패/빈 결과 판정, EPUB 출력, 업로드 대상·오류, 파일 다운로드, 백업 pull/push, watchdog 큐, 웹 인증·응답, OPDS 경로 방어, 스케줄 명령 생성, 업데이트 검증·실패 UI다. RSS/YouTube·공통 scraper 및 요약·번역 경로를 읽었으며 나머지 사이트별 처리는 주로 기존 픽스처 테스트로 보완했다. 모든 scraper의 실서비스 응답을 검증한 것은 아니다.

CodeGraph 초반 응답에는 pending-sync 경고가 있었고, 일부 응답은 소스 중간을 생략하거나 출력 예산으로 잘렸다. 경고 파일과 확인하지 못한 블록은 현재 파일 직접 열람·제한적 `rg`로 보완했다. CodeGraph 관계는 정적 분석의 best-effort이며 실제 콜백 실행·예외 전파를 보장하지 않는다. 최종 이슈는 해당 production caller와 별도 재현으로 다시 확인했다.

### 실제 실행한 검증

기존 설정·DB·dist를 사용하지 않도록 Git 추적 파일만 임시 디렉터리 `C:/Users/soulb/AppData/Local/Temp/x3-functional-audit-v53wv351`로 복사했다. 설치나 OS 작업 등록, 실제 기기 접속, 실제 업데이트 교체는 수행하지 않았다. 추가 프로브는 이 임시 복사본에만 작성했다.

환경: Windows, Python 3.14, 설치된 CustomTkinter 6.0.0. 기본 `python`은 3.11.9였지만 pytest가 없어 첫 시도는 테스트 수집 전에 실패했다. 이후 이미 설치된 `py -3.14`를 사용했다. CI의 Python 3.12와 동일 환경은 아니다.

| 검증 | 실제 결과 |
|---|---|
| `python -m pytest tests/ -q --tb=short -ra` | 기본 Python에 pytest 없음; 미실행으로 처리 |
| `py -3.14 -m pytest tests/ -q --tb=short -ra` | **265 passed, 6 failed**, 17.61초 |
| `py -3.14 -m pytest tests/test_opds.py tests/test_web_dashboard.py -q --tb=short -ra` | 실패 영역 재확인: **9 passed, 7 failed**, 13.87초 |
| `py -3.14 x3_websync.py --smoke` | 종료 코드 0, v1.1.0 smoke OK |
| `audit_probes.py` | 설정 변경 유실, 부분 파일 잔존, 로그인 IncompleteRead, watcher 작업 소멸, 업데이터 NameError 재현 |
| `audit_flow.py` | RSS 픽스처 → 실제 EPUB ZIP 검증 → 모사 업로드 → 실제 SQLite → 실패 기기만 재전송 → 중복 스킵 검증 |

전체 스위트 최초 실패는 OPDS의 catalog/인증/한글 파일명 3건, 대시보드의 인증/실행 중 응답/로그인 쿠키 3건이었다. 모두 `ConnectionResetError [WinError 10054]`를 보고했다. 재실행에서는 실패 테스트 집합이 달라졌다. **이 연결 재설정의 원인은 이번 감사에서 특정하지 못했다.** 이를 OPDS 인증 우회나 경로 방어 실패로 분류하지 않았다. 로그인 응답 길이 문제는 별도 loopback HTTP 요청과 메모리 기반 HTTP 파서로 확정했으며, 모든 연결 재설정을 그 문제로 설명하지 않는다.

통합 프로브는 첫 실행에서 기능 assertion을 모두 통과했으나 임시 SQLite 파일 정리 시 WinError 32가 발생했다. 테스트 종료부에 `gc.collect()`를 넣어 재실행하자 기능 assertion과 정리 모두 통과했다. 이는 애플리케이션 수정이 아니라 임시 프로브 정리 보완이다. 연결 수명 문제는 §5에 별도로 기록한다.

### 미검증 영역과 반증 결과

- 실제 X3의 업로드·읽기·이동·삭제, 실제 SD 카드 장애, Wi-Fi 단절 후 기기 내부 파일 상태는 미검증이다.
- macOS/Linux 실기동, 실제 schtasks/launchd/crontab 등록, frozen EXE 전체 UI·업데이트 교체, 실제 클라우드 충돌은 미검증이다.
- 실제 Calibre 라이브러리, 온라인 scraper, AI/번역 API, watchdog OS 이벤트의 완전한 E2E는 수행하지 않았다.
- GUI는 실제 숨긴 CTkProgressBar와 직접 callback 프로브를 사용했다. 전체 앱을 조작하는 GUI E2E는 수행하지 않았다.
- `progress_bar['value']` 때문에 즉시 동기화가 시작되지 않을 것이라는 후보는 현 설치 환경에서 파이프라인 호출이 실제 시작되어 **제외**했다.
- `ChunkedEncodingError`가 다운로드 GUI까지 미처리 전파된다는 후보도 **제외**했다. 설치된 requests에서 OSError 계열로 잡혀 `DeviceClientError`로 변환됐다. 실제 문제는 이미 덮어쓴 파일의 복구 부재다.
- SQLite 배치 기록에는 transaction, 복합 키, timeout이 있고, 뉴스 파이프라인에는 프로세스 락이 있다. 일반적인 동시 뉴스 실행에 따른 무조건적 DB 중복·손상을 주장하지 않는다.
- OPDS의 공개 설정은 GUI에서 인증을 강제하며 경로 정규화 방어가 있다. 비활성·레거시 scraper를 현재 정상 경로의 보안 문제로 취급하지 않았다.

## 4. High-Risk Issues

이 절은 확정된 기능·안정성 이슈 목록이다. 절 제목과 별개로 개별 우선순위를 명시했으며 Medium 항목을 High로 올리지 않았다. Speculative 항목은 포함하지 않았다.

### [ISSUE-001 — Resolved] 설정의 read-modify-write와 revision 검사가 프로세스 간 원자적이지 않음

- **위치:** `websync/config/manager.py:17`, `save_config:302`, `update_config:323`, `_save_config_unlocked:336`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 클래스의 `threading.Lock`은 같은 프로세스의 스레드만 막는다. 서로 다른 프로세스는 같은 설정을 읽고 각각 수정·저장할 수 있다. `save_config`의 revision 조회와 실제 replace 사이도 프로세스 락으로 보호되지 않는다. 저장 임시 경로 역시 항상 `config.json.tmp`로 같다.
- **발생 조건:** GUI가 설정을 변경하는 동안 예약 `--sync` 프로세스가 백업 메타데이터/사이트를 저장하는 등, 같은 설치 경로에서 설정 writer가 겹치는 경우.
- **영향:** 양쪽이 성공해도 먼저 저장한 변경이 사라질 수 있다. 설정·구독 변경이 유실되며 고정 임시 파일 충돌은 저장 오류를 추가로 만들 수 있다. 이번 재현으로 JSON 자체의 바이트 손상까지 확정한 것은 아니다.
- **근거:** 임시 config에 두 실제 자식 프로세스가 `update_config`를 수행하도록 했다. 두 mutator 진입 후 barrier로 읽기 완료를 맞추고 A, B 순서로 저장했다. A는 `audit_a`, B는 `audit_b`만 변경했으나 최종 결과는 `audit_a=None`, `audit_b=changed`, 두 프로세스 종료 코드는 모두 0이었다.
- **반증 확인:** 파이프라인 락은 동기화 실행끼리를 보호한다. GUI `_safe_save_config`와 설정 관리자 전체에는 이 락이 없다. 백업 폴더 락도 일반 GUI 설정 writer를 포함하지 않는다. `os.replace`는 파일 교체의 원자성만 제공하고 읽기·수정·revision 확인 전체를 직렬화하지 않는다. `.bak`은 자동 병합이나 유실 방지가 아니다.
- **호출/영향 범위:** CodeGraph의 ConfigManager caller는 GUI, SyncService, BackupSyncService, 로컬 sidecar import다. `GUI 설정 저장 → save_config`와 `CLI → pipeline → backup → update_config`가 교차한다.
- **권장 수정 방향:** config 경로별 OS 파일 락 안에서 최신 읽기·revision 확인·mutator·저장을 끝낸다. 임시 파일은 writer별 고유 이름을 사용한다. 충돌 병합도 변경 필드 단위로 수행하고, 이전 snapshot 전체를 최신 설정에 덮지 않도록 한다.
- **필요한 회귀 테스트:** 두 프로세스가 서로 다른 필드를 동시에 변경하면 둘 다 보존되어야 한다. 같은 revision 기반 CAS는 한쪽만 성공하거나 최신 상태로 재시도해야 한다. 저장 중 강제 실패에서도 기존 config가 파싱 가능하고 임시 파일이 다른 writer를 방해하지 않아야 한다.

### [ISSUE-002 — Resolved] 다운로드 실패 전에 기존 PC 파일을 잘라내어 원본을 훼손함

- **위치:** `websync/upload/device_client.py:259` `X3DeviceClient.download`, 특히 291–298행; `websync/gui/device_files/actions.py:224` `_download_selected`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** HTTP 200 이후 최종 목적 파일을 바로 `open(local_path, 'wb')`로 연다. 성공 여부가 결정되기 전에 기존 파일을 truncate하며, 전송 중 오류가 발생해도 이전 파일 복원이나 부분 파일 격리가 없다.
- **발생 조건:** PC 폴더에 동명의 파일이 있는 상태에서 기기 파일을 다운로드하고, 응답 본문 수신 중 연결 오류·저장 실패가 발생하는 경우. GUI는 폴더만 선택하며 개별 파일 덮어쓰기 여부를 묻지 않는다.
- **영향:** 기존의 완전한 전자책이 부분 다운로드로 바뀐다. 원본이 별도로 없다면 해당 로컬 내용은 유실된다. 새 파일인 경우에도 실패한 부분 파일이 정상 확장자로 남는다.
- **근거:** 임시 목적 파일에 `original-complete-book`을 쓴 뒤 HTTP response를 모사하여 `partial-new` 청크와 `ChunkedEncodingError`를 발생시켰다. API는 `DeviceClientError`를 반환했지만 디스크에는 `partial-new`만 남았다.
- **반증 확인:** 상태 코드 확인은 본문 수신 완료 이전에 수행된다. 예외 래핑과 GUI 오류 안내는 존재하며 이번 예외도 정상 변환됐다. 그러나 안내만으로 이미 사라진 기존 바이트를 복구할 수 없다. 상위 GUI에도 백업·임시 파일 저장 wrapper가 없다.
- **호출/영향 범위:** CodeGraph로 찾은 기기 API의 download 경로와 상위 `_download_selected → worker → client.download → _download_finished`를 확인했다. 기기 파일 탭의 PC 다운로드에 영향이 있으며 뉴스 업로드 DB 기록 문제와는 구별된다.
- **권장 수정 방향:** 목적 폴더의 고유 임시 파일에 다운로드하고 응답 완료·가능한 크기 검증 후 원자적으로 교체한다. 실패 시 임시 파일만 정리하고 기존 파일은 보존한다. GUI에는 동명 파일 충돌 정책을 제공한다.
- **필요한 회귀 테스트:** 기존 파일이 있을 때 첫 청크 후 연결 오류/디스크 오류를 주입하면 기존 바이트가 그대로 남아야 한다. 새 다운로드 실패 시 최종 파일이 없어야 한다. 정상 완료 시에만 새 내용으로 교체되어야 한다.

### [ISSUE-003 — Resolved] 웹 로그인 성공 응답의 Content-Length가 실제 본문과 다름

- **위치:** `websync/servers/dashboard/handler.py:139–153` `DashboardHandler.do_POST`; `websync/servers/templates/login.html`의 `login()`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 로그인 성공 응답은 `Content-Length: 18`을 보내지만 `b'{"ok": true}'`는 12바이트다. 브라우저 UI는 `await r.json()` 완료 후 `/dashboard`로 이동하므로 잘린 응답으로 처리되면 정상 로그인 전환을 완료하지 못한다.
- **발생 조건:** 유효한 토큰으로 `/api/login`에 정상 로그인하는 경우. 공격성 입력이나 특수 설정이 필요하지 않다.
- **영향:** 쿠키가 설정되었더라도 응답 본문 읽기가 실패하여 웹 로그인 화면에서 오류가 난다. 쿠키를 받은 뒤 직접 dashboard로 이동하는 우회 가능성과 별개로 기본 로그인 동선이 잘못되어 있다.
- **근거:** 실제 loopback 서버에 HTTP POST를 보내 `200`, 길이 `18`을 받은 뒤 `IncompleteRead(12 bytes read, 6 more expected)`를 확인했다. 같은 production handler를 메모리 출력에 연결하고 표준 HTTP 파서로 읽어도 동일했다. 브라우저 자체 E2E는 수행하지 않았다.
- **반증 확인:** BaseHTTPRequestHandler가 수동 지정한 Content-Length를 자동 수정하지 않는다. 세션·토큰 검증은 정상적으로 이 분기에 도달하게 할 뿐 framing 오류를 막지 못한다. 다른 API의 `_send_json`은 길이를 계산하지만 로그인 성공 분기는 이 helper를 사용하지 않는다.
- **호출/영향 범위:** CodeGraph의 `SettingsServersMixin._toggle_web → WebDashboard → DashboardHTTPServer → DashboardHandler.do_POST`와 로그인 HTML의 fetch 소비 경로. 뉴스 CLI 실행 자체는 영향받지 않는다.
- **권장 수정 방향:** 직렬화한 body를 한 번 만들고 `len(body)`로 헤더를 계산한다. 쿠키 설정이 가능한 공통 JSON 응답 helper를 이용한다.
- **필요한 회귀 테스트:** 유효 토큰 POST 후 헤더뿐 아니라 본문 전체를 읽고 JSON을 파싱해야 한다. 선언 길이=실제 UTF-8 바이트 수와 세션 cookie로 `/dashboard` 접근 성공을 함께 검사한다.

### [ISSUE-004 — Resolved] 복사 중인 감시 파일이 안정성 검사에서 탈락하면 재시도되지 않음

- **위치:** `websync/watch/calibre.py:64–78` `_flush_pending`, 92–104행의 watchdog handler.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** debounce 후보를 `_pending`에서 먼저 삭제한 뒤 `_is_file_stable`로 검사한다. 불안정한 파일은 다시 큐에 넣지 않으며, 등록된 이벤트 처리는 on_created/on_moved뿐이다.
- **발생 조건:** 최종 `.epub`/`.pdf` 이름으로 큰 파일을 복사하고, debounce 2초 및 이후 크기 확인 구간에도 파일 크기가 증가하는 경우. 완료 후 새 create/move 이벤트 없이 modify 이벤트만 발생하면 누락된다.
- **영향:** 정상적으로 복사를 마친 전자책도 자동 전송되지 않는다. 사용자가 직접 전송하거나 파일을 이동·재생성해야 한다.
- **근거:** pending 파일 하나에 안정성 검사 False를 주입하여 flush한 뒤, True로 바꾸고 다시 flush했다. 결과는 `_pending={}`, 콜백 목록 `[]`였다. OS의 특정 이벤트 발생 빈도는 모사하지 않았으며 큐에서 작업이 소멸하는 로직을 검증했다.
- **반증 확인:** debounce와 크기 검사 자체는 부분 파일 업로드를 줄이는 보호 장치다. 그러나 실패 후보의 재등록·수정 이벤트·정기 재검색이 없다. GUI의 직렬 업로드 worker는 콜백으로 전달받지 못한 파일을 복구할 수 없다. 임시 확장자에서 최종 이름으로 rename하는 프로그램은 정상 동작할 수 있으므로 모든 파일 생성이 실패한다고 보지 않는다.
- **호출/영향 범위:** CodeGraph의 `_toggle_watch → CalibreWatcher.start → _Handler → _schedule_debounced → _flush_pending → on_new_file → upload worker`에서 콜백 이전 단계가 유실 지점이다.
- **권장 수정 방향:** 성장 중인 후보를 제한된 backoff로 다시 검사하거나 modify/close 이벤트와 연계한다. 재검사 대기열과 전송 중 파일을 구분하여 중복 enqueue도 막는다.
- **필요한 회귀 테스트:** 첫 검사 동안 성장하고 이후 안정화되는 파일이 최종적으로 정확히 한 번 전송되어야 한다. 삭제된 파일은 정리되고, 감시 중지 시 재검사 타이머가 새 작업을 만들지 않아야 한다.

### [ISSUE-005 — Resolved] 업데이터 예외를 지연 콜백에서 참조하여 실패 UI 복구가 중단됨

- **위치:** `websync/gui/settings_tab/updater.py:145–156` 확인 worker, 199–219행 다운로드 worker, 특히 154·217행.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** `except Exception as exc` 안에서 `lambda: ...str(exc)`를 만들어 `_safe_ui`로 예약한다. Python은 except 블록 종료 시 예외 변수 binding을 지우므로 이후 Tk callback 실행 시 `NameError`가 난다.
- **발생 조건:** 업데이트 확인의 네트워크·서명 오류 또는 다운로드의 일반 예외 이후, 예약한 callback이 except 블록이 끝난 다음 실행되는 정상적인 비동기 일정.
- **영향:** `_on_update_check_failed`/`_on_download_failed`가 호출되지 않아 실패 안내와 버튼 상태 복구가 생략된다. 이미 disabled된 확인 버튼이 비활성 상태에 남을 수 있다.
- **근거:** 실제 `_on_check_update_clicked`를 호출하고 UpdateService에 `RuntimeError('offline')`을 주입했다. UI callback을 큐에 보관했다가 worker 종료 후 실행하자 `NameError: cannot access free variable 'exc' ...`가 발생했고 실패 UI 호출 수는 0이었다. 다운로드 실패 경로도 동일한 closure를 사용한다.
- **반증 확인:** `_safe_ui`의 try/except는 `after` 예약 시점만 감싼다. 나중에 실행되는 lambda의 변수 해석 실패를 잡거나 바인딩을 보존하지 않는다. 명시적 취소 분기는 예외 변수를 캡처하지 않아 이 문제와 구별된다. 테스트에서 네트워크나 실제 설치는 수행하지 않았다.
- **호출/영향 범위:** CodeGraph의 `_on_check_update_clicked → worker → _safe_ui → 실패 callback`, `_start_update_download → download_worker → _safe_ui` 경로. 서명 검증을 우회하는 문제는 아니다.
- **권장 수정 방향:** except 안에서 문자열을 먼저 만들고 기본 인자/partial 등으로 값을 바인딩한다. 성공·실패·취소 모두 terminal 상태에서 버튼과 진행 UI를 일관되게 복구한다.
- **필요한 회귀 테스트:** worker가 완전히 끝난 뒤 queued callback을 실행하는 테스트에서 네트워크 오류·서명 오류·다운로드 오류가 각각 표시되고 버튼이 normal이 되어야 한다. 즉시 실행하는 fake callback만으로 검증하지 않는다.

## 5. Potential Functional Gaps

- **Confirmed Gap → Resolved — 공유 데이터 삭제 전파.** 사이트와 동기화 이력에 timestamp tombstone을 추가했다. stale 원격 항목 복원 방지, 수동 import/export, delete-only 병합을 회귀 테스트로 검증했다.
- **Confirmed Gap → Resolved — 종료·재시작 작업 복구.** 감시 업로드 대기 목록을 config에 영속화하고 앱 시작 시 재처리한다. 종료 시 감시 worker와 HTTP 서버 자원을 정리한다. 전송 성공과 DB 기록 사이의 강제 프로세스 종료는 안전한 중복 가능성이 남으며 데이터 유실로 처리하지 않는다.
- **Confirmed Gap → Resolved — DB 연결 종료.** context manager가 commit/rollback 뒤 connection을 항상 닫는다.
- **Confirmed Gap → Resolved — 업데이트 다운로드 메모리.** 청크를 staging 검증기에 직접 전달하여 artifact 전체를 중복 보관하지 않는다.
- **Likely Gap → Resolved — 실행 설정 snapshot.** 전체·선택 파이프라인은 시작 시 config 및 교체 가능한 서비스 참조를 고정하고 다음 실행부터 새 설정을 반영한다.
- **추정 → 문서화 — 완전한 오프라인 이미지 지원.** 현재 옵션은 원격 `<img>` 참조 보존 의미이며 이미지 파일의 EPUB 내장과 오프라인 표시를 보장하지 않는다. 요구가 확인되면 별도 기능으로 설계한다.

## 6. Documentation Mismatches

아래 표는 감사 시점에 확인한 불일치 기록이다. 후속 개선에서 모두 수정했으며 현재 문서는 RSS 입력 형식, 선택 기능의 배포 범위, 공유 동기화의 한계와 삭제 전파, 안정 기기 ID/alias, 프로세스 락을 실제 동작대로 설명한다.

| 문서의 설명 | 확인한 구현 및 차이 |
|---|---|
| README YouTube URL 예시 `https://www.youtube.com/@채널명`, 채널/영상 지원 | `YoutubeScraper.fetch_articles:12–22`는 입력을 직접 XML로 파싱하고 `entry`를 찾는다. handle URL·watch URL을 채널 RSS로 변환하는 분기가 없다. 현재 구현에는 `feeds/videos.xml?channel_id=...` 형식 안내가 필요하다. |
| README의 EXE 권장 경로와 YouTube·폴더 감시·표지·Google 번역 소개 | `x3_websync.spec`가 PIL, youtube_transcript_api, watchdog, googletrans를 명시적으로 제외한다. release workflow도 필수 requirements만 설치한다. 소스 실행의 선택 기능과 경량 EXE의 지원 범위를 구분해야 한다. |
| README “공유 폴더로 완벽하게 동기화”, 어느 PC에서든 중복 방지 | 구현은 로컬 JSON union이며 각 PC의 클라우드 복제본 사이 OS 락은 분산 락이 아니다. 오프라인 동시 실행·동기화 지연·삭제 전파까지 보장하지 않는다. |
| README 이력에서 삭제한 다음 다시 동기화하면 재전송 | 공유 이력 pull이 활성화되어 있으면 union import로 삭제한 이력이 복원될 수 있다. 공유 모드의 재전송 절차를 별도로 설명해야 한다. |
| GUI “기기별 이력 (같은 리더기만 스킵)” 및 README 기기별 관리 | `SyncHistoryDb.needs_sync:156–158`은 대상 그룹이 하나이면 다른 기기의 이력이라도 `is_synced(url)`로 스킵한다. 주소 변경 호환 의도는 명시돼 있으나, 다른 리더기로 교체한 경우까지 같은 의미는 아니다. 안정 ID가 있을 때의 정책을 명확히 해야 한다. |
| CLAUDE 동시 기동의 config 손상 해결책으로 threading.Lock 제시 | 동일 프로세스 내부에 한정된 보호다. 프로세스 간 설정 변경 유실은 ISSUE-001처럼 남아 있다. |

문서의 초기 로드맵 중 “이미 완료”라고 명시된 과거 제안 자체를 미구현 버그로 중복 지적하지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 설정 read-modify-write와 revision 검사 전체를 동일 config 경로의 프로세스 락으로 직렬화하고 고유 임시 파일을 쓴다. GUI·백업·CLI writer를 모두 포함한다.
2. **ISSUE-002:** 다운로드를 임시 파일에 끝까지 저장한 뒤 교체한다. 기존 파일 보존을 장애 주입 테스트의 합격 조건으로 삼는다.
3. **ISSUE-003:** 로그인 body 길이를 실제 바이트 수로 계산하고 body 소비까지 검증한다.

### Phase 2 — Stability

1. **ISSUE-004:** 성장 중 파일의 재검사 및 감시 업로드 실패 재시도 정책을 추가한다.
2. **ISSUE-005:** 지연 callback에 예외 문자열을 값으로 바인딩하고 실패·취소 후 UI 상태를 복구한다.
3. DB connection의 명시적 종료, 서버 shutdown 이후 socket 정리, 작업 종료의 대기·취소·복구 경계를 검증한다.
4. 연결 재설정 테스트 실패를 동일 Windows 환경과 CI Python 3.12에서 비교해 원인을 분리한다. 테스트 성공으로 간주하거나 단순 재시도로 숨기지 않는다.
5. 공유 데이터 삭제·단일 기기 이력 정책을 결정하고 문서를 실제 동작에 맞춘다.

### Phase 3 — Structural

1. 한 번의 파이프라인 실행에 immutable config/대상/이력 키 snapshot을 전달하여 실행 중 설정 변경과 분리한다.
2. 파일 I/O·HTTP response·GUI callback 경계를 주입 가능하게 유지하고, 응답 헤더/함수 호출 여부가 아닌 최종 결과를 테스트한다.
3. 선택 기능을 포함하는 빌드와 경량 빌드의 capability 목록을 UI·README·배포 smoke 검사에 함께 적용한다.
4. 공유 데이터의 이벤트/삭제 기록과 영속 작업 큐는 실제 다중 PC 사용 요구에 맞춰 도입한다. 단순 구조 취향의 리팩터링은 우선하지 않는다.

위 계획은 후속 개선에서 모두 수행했다. Phase 3의 오프라인 이미지 내장은 제품 요구가 확인되지 않은 추정 항목이므로 현재 의미를 문서화하는 것으로 처리했다.

## 8. Test Recommendations

| 종류 | 입력·조건 | 기대 결과 |
|---|---|---|
| Unit / Regression — ISSUE-003 | 유효 토큰으로 로그인 handler 실행, 응답 전체 파싱 | Content-Length가 body byte 수와 같고 JSON·세션 cookie 모두 유효 |
| Unit / Regression — ISSUE-005 | UpdateService가 timeout/검증 예외를 발생; worker 종료 후 UI queue 실행 | NameError 없이 오류 표시, 확인 버튼 normal, 다운로드 취소 UI 정리 |
| Unit — ISSUE-004 | 크기 검사 결과 False, False, True; 실제 파일명은 .epub | 재검사 대기 유지 후 최종 callback 정확히 1회 |
| Integration — ISSUE-002 | 기존 목적 파일 + 첫 청크 성공 후 연결 오류/디스크 쓰기 오류 | 기존 파일 byte-for-byte 보존, 임시 파일 정리, GUI에 실패 표시 |
| Concurrency — ISSUE-001 | 같은 config에 실제 두 프로세스의 서로 다른 필드 수정 | 두 변경 보존; CAS 충돌은 명시적 재시도/거부, 유효 JSON 유지 |
| Concurrency — 설정 snapshot | scraper 대기 중 GUI가 기기 주소/출력 경로 변경 | 현재 실행은 기존 snapshot으로 일관되고 다음 실행부터 새 설정 반영 |
| Integration — 핵심 뉴스 | RSS 1건, 기기 A 성공/B 실패 → 두 번째 실행 B 성공 → 세 번째 실행 | 첫 실행 실패 기기 이력 없음, 재시도는 B만, 마지막은 upload 0회 |
| Integration — DB 오류 | 업로드 성공 후 mark_synced_many에 실패 주입 | 성공으로 오보하지 않음, DB batch 부분 커밋 없음, 재실행 정책 명확 |
| Integration — 공유 데이터 | PC A에서 구독/이력 삭제, B와 cloud에 이전 항목 존재 | 결정된 삭제/재전송 정책대로 동작하고 복원·충돌을 사용자에게 설명 |
| End-to-End — 웹 | 실제 브라우저 로그인 → 동기화 → 실행 중 재요청 → 취소 → 상태 조회 | 정상 redirect, 202/409 구분, 실행 상태·최종 결과와 화면 일치 |
| End-to-End — 기기 | 테스트용 X3에서 생성 EPUB 전송 후 목록 조회·열기 | 파일명·경로 정상, 한글 본문/목차 가독성, 실제 수신 확인 |
| Concurrency — GUI/CLI/Watch | 세 경로를 동시에 실행, Watch 파일 복사는 30초 이상 지연 | 뉴스 중복 실행 거부, Watch 작업은 정책에 따라 보존·재시도, 조용한 유실 없음 |
| Regression — 종료 복구 | 업로드 중 종료, 업로드 성공/DB 기록 전 종료를 각각 모사 | 기존 파일 보존, 다음 기동의 재시도·중복 처리 정책 확인 |
| Platform-specific | Windows 한글·공백 경로, Linux/macOS 스케줄 명령·실기동 | 경로와 인자 보존, 설정/로그 위치 일치; 테스트 계정에서만 등록·해제 |
| Platform-specific — DB | Windows에서 DB 작업 반복 후 연결 종료·파일 rename | GC 강제 호출 없이 파일 핸들 해제, 미종료 connection 경고 없음 |
| Build / Regression | 필수 패키지만 있는 frozen EXE와 선택 패키지 소스 환경 | 미지원 기능의 명확한 안내; 지원 기능은 실제 실행; smoke와 전체 GUI 차이 검사 |

기존 `test_login_sets_session_cookie`는 헤더만 확인하고 body를 읽지 않아 ISSUE-003을 놓친다. `test_calibre_watch_handles_moved_epub`는 테스트 안에서 on_moved 로직을 재작성하여 호출하므로 production handler의 실제 이벤트 연결과 성장 파일 재시도 부재를 검증하지 못한다. 이 두 테스트를 최종 사용자 결과까지 검사하도록 강화하는 것이 단순 테스트 수 증가보다 중요하다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Good | 확인된 로그인·감시·업데이트 실패 경로를 수정하고 최종 결과 중심 회귀 테스트를 추가했다. |
| Runtime Stability | Acceptable | DB/HTTP/감시 종료와 실행 snapshot을 보완했다. 실제 외부 서비스·장시간 GUI 운용 검증은 남아 있다. |
| Data Integrity | Good | 설정 원자성, 다운로드 원본 보존, 공유 삭제 tombstone을 구현하고 장애·동시성 테스트로 검증했다. |
| Error Resilience | Acceptable | 감시 재시작 복구와 updater 오류 UI를 보완했다. 네트워크 정책은 각 외부 API의 기존 timeout/error 경계를 유지한다. |
| Cross-platform Robustness | Acceptable | 경로·파일 교체·명시적 close를 이식 가능한 표준 API로 구현했지만 이번 후속 검증은 Windows에서만 수행했다. |
| Test Confidence | Good | 감사 재현을 독립 회귀 테스트로 고정했으며 전체 pytest와 Python compile 검증 결과를 후속 상태에 기록한다. |

**우선 수정 대상으로 제시했던 설정 저장 원자성, 다운로드 원본 보존, 웹 로그인 응답 길이는 모두 수정됐다.** 다음 운영 검증 우선순위는 테스트용 X3 실기기 전송, 실제 클라우드 동기화 충돌, Linux/macOS의 스케줄러·파일 감시다.
