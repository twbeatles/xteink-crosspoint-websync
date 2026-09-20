# Project Audit

감사일: 2026-09-20

기준: `main` / `a290acc` / Windows / Python 3.14.7
범위: 기능 구현, 런타임 안정성, 데이터 무결성, 오류 복구, 주요 보안 경계. 스타일·네이밍·취향성 리팩터링은 제외했다.

## Remediation Status — 2026-09-20

이 문서 아래의 내용은 수정 전 감사 스냅샷이며, 이후 다음 조치를 구현했다.

- **ISSUE-001 해결:** 공유 JSON의 missing과 invalid/partial 상태를 구분하는 strict reader를 추가했다. sites/history 파일을 모두 선검증하고 제한적으로 재시도한 뒤, 손상 상태면 push/pull을 중단하여 원본을 덮어쓰지 않는다.
- **ISSUE-002 해결:** 신규 history/tombstone/site 시각을 UTC `Z` 형식으로 기록하고, SQLite UTC·offset·legacy local naive 시각을 절대시간으로 비교한다. 삭제 후 재전송한 최신 이력이 이전 tombstone으로 다시 삭제되지 않는 회귀 테스트를 추가했다.
- **ISSUE-003 해결:** 자동 동기화와 선택 동기화의 per-site/digest 경로 모두 기기별 missing article set을 계산하고, 동일 집합의 기기만 묶어 별도 EPUB을 생성·전송·기록한다.
- **ISSUE-004 해결:** OPDS의 파일명·제목을 XML escape하고 파일 mtime을 UTC로 출력한다. `A&B.epub` 카탈로그를 표준 XML parser로 검증한다.
- **안정성 보완:** GUI 장기 작업을 공통 thread registry로 추적하고 종료 시 서비스 취소, 서버/watcher 중지, worker 대기를 수행한다. 공개 scraper URL이 redirect를 통해 loopback/private 주소로 진입하는 경로도 차단한다. 명시적으로 설정한 로컬 source는 계속 허용한다.
- **검증 결과:** `python -m pytest -q` — **307 passed in 19.58s**. `python x3_websync.py --smoke` — **v1.2.1 smoke check OK**.

실제 X3/X4 펌웨어의 중단된 multipart 처리, 실제 클라우드 동기화 클라이언트의 순간 파일 상태, OS별 frozen 배포물은 로컬 자동 테스트로 검증할 수 없어 운영 환경 검증 항목으로 남아 있다.

## 1. Executive Summary

이 프로젝트의 기본 단일 기기 흐름은 전반적으로 잘 구성되어 있다. 스크래핑 URL 검증, 사이트별 예외 격리, EPUB 생성, 업로드 성공 기기만 이력 기록, 프로세스 간 파이프라인 락, 설정 원자 교체, 업데이트 서명 검증이 구현되어 있고 전체 테스트 **299개가 통과**했다.

다만 전체 평가는 **Needs Work**다. 특히 **공유 데이터 폴더 기능을 사용하는 환경은 High Risk**로 본다. 임시 데이터로 실제 실행한 재현에서 공유 JSON 손상 시 원격 데이터를 덮어쓰는 동작과, 한국 시간대에서 삭제 후 재전송한 이력이 오래된 tombstone에 다시 제거되는 동작을 확인했다.

가장 중요한 문제는 다음과 같다.

1. **공유 폴더의 0바이트·손상 JSON을 “파일 없음”으로 처리한 뒤 정상 push로 덮어쓴다.** 원격에만 있던 구독·이력은 복구할 자료 없이 사라질 수 있다.
2. **SQLite 전송 시각은 UTC인데 삭제 시각은 로컬 naive 시각이다.** UTC+9 환경에서 삭제 후 즉시 재전송해도 원격 tombstone을 다시 읽으면 최신 전송 이력이 삭제된다.
3. **다중 기기의 누락 기사 집합이 서로 다를 때 기기별 EPUB을 만들지 않는다.** 한 기기에 이미 보낸 기사까지 포함한 공통 EPUB을 각 기기에 전송하여 “중복 없는 전송” 약속을 위반한다.
4. **OPDS 출력 폴더에 `&` 같은 문자가 든 EPUB 파일명이 있으면 카탈로그 XML이 깨진다.** 생성 EPUB의 정상 경로에서는 파일명이 정리되므로 영향은 제한적이다.

**데이터 손상/유실 가능성:** 있다. ISSUE-001은 공유 폴더에만 있던 `sites.json`·`synced_posts.json` 내용을 덮어쓸 수 있다. ISSUE-002는 물리적 EPUB을 지우지는 않지만 최신 전송 이력을 유실시켜 중복 전송과 삭제 전파 오류를 만든다. 기본 뉴스 파이프라인에서 업로드 실패를 성공으로 기록하는 경로는 확인하지 못했다.

**가장 먼저 수정할 영역:** `backup/atomic_io.py`의 읽기 결과 모델, `db/history.py`의 시각 저장·비교 규칙, 다중 기기용 기사 배치 생성 순서다.

## 2. Project Understanding

### 프로젝트 목적

XTEINK X3/X4 및 CrossPoint 호환 리더용 데스크톱 동기화 앱이다. RSS·웹·뉴스레터·YouTube 자막을 수집해 EPUB으로 만들고, 기기 HTTP API로 무선 전송한다. SQLite 이력으로 증분 동기화하며 Calibre, 기기 파일 관리, 일정 등록, OPDS, 웹 대시보드, 공유 폴더 백업, 자동 업데이트를 제공한다.

### 주요 entrypoint

- `x3_websync.py:47` `main()`
  - `--sync`: 헤드리스 전체 동기화
  - `--smoke`: 핵심 모듈과 i18n 카탈로그 확인
  - `--check-update`: 서명된 업데이트 매니페스트 확인
  - `--apply-update`: 스테이징 바이너리 교체 헬퍼
  - 기본 실행: GUI 단일 인스턴스 락 후 `SyncAppGui`
- GUI 즉시 동기화: `websync/gui/app_core/sync_control.py:37`
- 웹 대시보드 동기화: `WebDashboard` → `SyncService.begin_sync_pipeline_async()`

### 핵심 모듈

| 영역 | 주요 모듈 |
|---|---|
| 설정 | `websync/config/manager.py`, `validator.py`, `secrets.py` |
| 파이프라인 | `pipeline/service.py`, `sync_pipeline.py`, `preview.py`, `selected_sync.py` |
| 수집 | `scrapers/` 13종, `factory.py`, `selector_assistant/` |
| EPUB | `epub/builder.py`, `sanitize.py`, `css.py`, `cover.py` |
| 업로드·기기 파일 | `upload/uploader.py`, `device_client.py`, `device_ids.py`, `remote_path.py` |
| 이력 | `db/history.py` |
| 공유 폴더 | `backup/service.py`, `atomic_io.py`, `format.py` |
| 외부 통합 | `integrations/calibre.py`, `watch/calibre.py`, `scheduler/manager.py` |
| 서버 | `servers/opds.py`, `servers/dashboard/` |
| 업데이트 | `core/update/`, `cli/update_apply.py` |
| GUI | `gui/app_core/`, `sync_tab/`, `device_files/`, `settings_tab/` |

### 데이터 저장 방식

- `config.json`: 프로세스 파일 락, revision CAS, 임시 파일 + `fsync` + `os.replace`
- `sync_history.db`: SQLite WAL, `(url, device_ip)` 기본키, 프로세스 내부 락, commit/rollback context manager
- `output/`: 생성 EPUB
- `logs/`: 일자별 회전 로그
- 공유 폴더: `sites.json`, `synced_posts.json`, `manifest.json`, 삭제 tombstone
- `.updates/`: 검증된 업데이트 스테이징 파일과 결과

### 외부 의존성

- 필수: `requests`, `beautifulsoup4`, `lxml`, `ebooklib`, `customtkinter`, `cryptography`
- 선택: Pillow, googletrans, youtube-transcript-api, watchdog
- 외부 시스템: CrossPoint HTTP API, 각 웹 소스, Calibre CLI, Windows Task Scheduler/launchd/crontab, 클라우드 동기화 클라이언트, OpenAI/Ollama/LibreTranslate

### 핵심 실행 흐름

```text
x3_websync.main / GUI / Dashboard
→ SyncService: 스레드 락 + ProcessFileLock
→ 공유 폴더 pull
→ config 스냅샷
→ ScraperFactory → fetch_url → 기사 정규화
→ SyncHistoryDb.needs_sync
→ 번역·요약(선택)
→ EpubBuilder.build / build_digest
→ X3Uploader.upload_to_targets
→ 성공 기기만 SyncHistoryDb.mark_synced_many
→ 공유 폴더 push
→ 결과·로그·알림
```

기기 파일 관리 흐름은 `GUI 입력 → normalize_remote_path → X3DeviceClient → CrossPoint API → GUI 결과`이고, 자동 업데이트는 `HTTPS 매니페스트 → Ed25519 검증 → 스트리밍 SHA-256 검증 → 헬퍼 교체 → --smoke → 실패 시 롤백`이다.

## 3. Audit Coverage & Limitations

### 확인한 주요 모듈

- 진입점, GUI/CLI 분기, GUI 단일 인스턴스와 파이프라인 프로세스 락
- 전체/프리뷰/선택 동기화, 취소, 결과 집계, 다중 기기 alias와 부분 재시도
- SQLite 스키마·마이그레이션·이력/tombstone import/export
- 공유 폴더 pull/push, 병합, 파일 락, 원자적 JSON 저장
- 설정 기본값 병합, 검증, revision CAS, 충돌 병합
- 업로더·기기 파일 API의 경로 정규화, timeout, 다운로드 임시 파일 교체
- 스크래퍼 공통 네트워크 세션, retry, 16MB 상한, 선택자 도우미 URL 안전 검사
- Calibre, watcher, 스케줄러, OPDS, 대시보드, 업데이트 검증·롤백
- README, README.ko, CLAUDE, USER_GUIDE, DEVELOPER, requirements, pytest/pyright 설정, PyInstaller spec, CI/release workflow

루트 `AGENTS.md` 파일은 저장소에 존재하지 않았다.

### CodeGraph로 분석한 호출 관계

CodeGraph를 일반 검색보다 먼저 사용해 다음 경로와 영향 범위를 확인했다.

- `x3_websync.main` → `SyncService.run_sync_pipeline` → `run_sync_pipeline_locked`
- `ScraperFactory.fetch_articles` → `article_sync_key` → `needs_sync`
- `resolve_pending_upload_ips` → `EpubBuilder` → `upload_to_targets` → `collect_mark_entries` → `mark_synced_many`
- `delete_entry` / `clear_all` → `export_deleted_posts` → `BackupSyncService.push/pull` → `import_deleted_posts` / `import_posts_union`
- GUI `_on_close`와 파이프라인·watch·Calibre·기기 파일 daemon worker의 종료 범위
- OPDS `_serve_catalog`의 출력 폴더·파일명 처리와 호출자
- 설정 `load_config` / `save_config` / `update_config` / `_safe_save_config`의 CAS와 호출자
- 업데이트 매니페스트 검증 → 스테이징 → 헬퍼 → smoke/rollback

### 실행한 테스트와 재현

- `python -m pytest -q` → **299 passed in 26.84s**
- `python x3_websync.py --smoke` → **v1.2.1 smoke check OK**
- 임시 SQLite DB에서 `mark → delete → mark → 이전 tombstone import` → 최신 전송 행이 다시 삭제됨
- 임시 공유 폴더의 손상된 `sites.json`·`synced_posts.json`에 `BackupSyncService.push(force=True)` → 성공으로 반환하며 두 파일을 로컬 내용으로 교체
- 임시 DB의 두 기기에 서로 다른 URL 이력을 넣고 전체 파이프라인 실행 → 두 URL이 든 같은 EPUB을 두 기기에 모두 업로드
- 임시 OPDS 폴더에 `A&B.epub` 생성 후 카탈로그 요청 → HTTP 200이지만 XML 파싱 실패

위 재현은 모두 임시 디렉터리·임시 DB·mock 기기를 사용했다. 저장소의 `sync_history.db`, 실제 기기, 실제 사용자 데이터는 변경하지 않았다.

### 확인하지 못한 환경

- 실제 X3/X4 및 펌웨어별 HTTP API 동작, 중단된 multipart upload의 기기 측 상태
- 실제 OneDrive/Google Drive/Dropbox 두 PC 동시 동기화 타이밍
- PyInstaller frozen 산출물 실행 및 자동 업데이트 실제 교체
- macOS launchd, Linux crontab, OS별 알림
- Calibre 실제 라이브러리와 watchdog 실파일 이벤트
- GUI 사람 조작 기반 end-to-end
- 외부 웹사이트의 현재 DOM/API 호환성

### 분석 한계

CodeGraph는 동적 Tk callback, 파일시스템 감시, OS 스케줄러와 실제 펌웨어의 동작을 완전히 모델링하지 못한다. 네트워크·클라우드 관련 결론은 코드 흐름과 임시 환경 재현을 결합했으며, 실제 외부 서비스 성공 여부를 검증한 것으로 표현하지 않는다.

## 4. High-Risk Issues

### [ISSUE-001] 손상되거나 부분 동기화된 공유 JSON을 정상 push가 덮어쓴다

- **위치:** `websync/backup/atomic_io.py:31-48` `read_json_safe`; `websync/backup/service.py:308-358` `_push_unlocked`
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** `read_json_safe()`는 파일 없음, 0바이트, JSON 파싱 실패, 인코딩 실패를 모두 `None`으로 반환한다. push는 `None`을 “원격 데이터 없음”으로 간주하여 병합 없이 로컬 사이트·이력으로 원격 파일을 다시 쓴다.
- **발생 조건:** 공유 폴더의 `sites.json` 또는 `synced_posts.json`이 클라우드 다운로드 중 0바이트/부분 상태이거나 실제로 손상된 순간에 자동/수동 push가 실행된다.
- **영향:** 해당 PC 로컬 캐시에 없는 다른 PC의 구독, 전송 이력, tombstone이 원격 정본에서 사라질 수 있다. 이후 구독 누락, 삭제 항목 부활, 대량 중복 전송으로 이어질 수 있다.
- **근거:** 임시 공유 폴더의 두 파일에 잘못된 JSON을 기록한 뒤 `push(force=True)`를 실행했다. 결과는 `ok: true`, `sites_written: true`, `history_written: true`였고 두 손상 파일은 로컬 1개 사이트·1개 이력만 든 정상 JSON으로 교체됐다.
- **반증 확인:** 쓰기는 tmp + `fsync` + `os.replace`라 같은 PC의 부분 쓰기를 줄인다. 공유 폴더 파일락도 있다. 그러나 읽기 실패 원인을 구분하지 않고, 락은 문서대로 PC 간 상호 배타를 보장하지 않는다. 원격 파일이 존재하지만 유효하지 않은 경우에도 push 중단·격리·재시도가 없다.
- **호출/영향 범위:** 전체 파이프라인 `_run_pipeline_body` 종료 push, GUI 사이트 변경 debounce push, 수동 `sync_now`, 앱 종료 `flush_backup_push`; 영향 파일은 `sites.json`, `synced_posts.json`, 이어서 `manifest.json`이다.
- **권장 수정 방향:** 읽기 결과를 `MISSING / VALID / INVALID_OR_PARTIAL`로 구분한다. push에서 기존 파일이 있는데 VALID가 아니면 절대 덮어쓰지 말고 실패/재시도 처리한다. 손상본을 timestamped quarantine 사본으로 보존하고, 클라우드 안정화 후 다시 읽는다.
- **필요한 회귀 테스트:** 기존 파일이 0바이트, 잘린 UTF-8, 잘못된 JSON, JSON scalar인 각 경우 push가 `ok: false`이고 원본 바이트가 바뀌지 않아야 한다. 실제 파일 없음일 때만 새 정본을 생성해야 한다.

### [ISSUE-002] 로컬 삭제 시각과 UTC 전송 시각 혼용으로 재전송 이력이 다시 삭제된다

- **위치:** `websync/db/history.py:83-90`, `238-280`, `343-380`, `440-485`, `487-590`
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** `synced_at` 기본값은 SQLite `CURRENT_TIMESTAMP`라 UTC지만, `delete_entry()`와 `clear_all()`은 `datetime.now().isoformat()`으로 로컬 naive 시각을 기록한다. `_time_key()`와 import 병합은 timezone 해석 없이 문자열로 비교한다.
- **발생 조건:** UTC와 다른 시간대에서 이력을 삭제해 재전송한 뒤, 공유 폴더에 남아 있던 이전 tombstone을 pull하거나 다음 push의 remote union 과정에서 다시 읽는다.
- **영향:** 실제로 더 최신인 재전송 이력이 삭제된다. 이후 같은 기기에 같은 기사가 다시 전송되며, 원격 tombstone도 계속 유지될 수 있다. UTC+9에서는 삭제 시각이 새 전송 UTC 시각보다 약 9시간 미래처럼 보인다. UTC 음수 오프셋에서는 반대로 정당한 삭제가 최신 전송보다 오래된 것으로 오판될 수 있다.
- **근거:** Asia/Seoul 환경의 임시 DB에서 삭제 tombstone은 `2026-09-20T09:11:09...`, 1초 뒤 재전송 행은 `2026-09-20 00:11:10`으로 저장됐다. 이전 tombstone을 `import_deleted_posts()`하자 재전송 행이 제거되어 export 결과가 빈 목록이 됐다.
- **반증 확인:** `mark_synced_many()`는 같은 키의 로컬 tombstone을 삭제한다. 그러나 push는 원격 JSON을 다시 읽어 tombstone을 import하므로 보호가 무효화된다. DB transaction과 기본키는 원자성·중복 행만 보호하고 시각 의미 오류는 막지 못한다.
- **호출/영향 범위:** History 탭의 선택 삭제/전체 초기화 → 선택 또는 전체 재동기화 → `mark_synced_many` → `BackupSyncService.pull/push` 및 이력 JSON 가져오기. CodeGraph상 `import_deleted_posts`는 backup/local import/History UI에서 호출된다.
- **권장 수정 방향:** 모든 신규 시각을 UTC timezone-aware ISO 8601(`...Z` 또는 `+00:00`)이나 정수 epoch로 저장한다. 비교 시 문자열이 아니라 timezone-aware `datetime`으로 파싱한다. 기존 SQLite 공백형 UTC와 기존 naive 로컬 tombstone에 대한 명시적 마이그레이션 규칙이 필요하다.
- **필요한 회귀 테스트:** UTC+9와 UTC-8 각각에서 `mark → delete → mark → old tombstone import` 후 최신 mark가 남아야 한다. 삭제 후 새 mark가 없으면 tombstone이 행을 제거해야 한다. 서로 다른 오프셋이 든 JSON import도 절대시간 기준으로 판정해야 한다.

### [ISSUE-003] 다중 기기의 서로 다른 누락 기사 집합을 공통 EPUB으로 보내 중복 기사가 전달된다

- **위치:** `websync/pipeline/sync_pipeline.py:147-158`, `187-236`, `263-314`; `websync/upload/device_ids.py:149-202`
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** `new_articles`는 “대상 중 한 기기라도 미전송”인 기사의 합집합이다. `resolve_pending_upload_ips()`는 그 배치 중 하나라도 빠진 기기를 고른다. 이후 EPUB은 기기별 누락 집합이 아니라 `new_articles` 전체로 한 번만 만들어 모든 pending 기기에 전송된다.
- **발생 조건:** 기기 A에는 기사 1만 있고 기기 B에는 기사 2만 있는 등 기기별 이력이 갈라져 있을 때 자동 전체 동기화를 실행한다. 부분 업로드 실패 후 다음 회차나 여러 PC/기기를 번갈아 쓰면 현실적으로 발생한다.
- **영향:** A는 이미 받은 기사 1을, B는 이미 받은 기사 2를 새 EPUB 안에서 다시 받는다. 저장 공간·배터리 절감과 “Zero Duplicate Delivery” 약속을 위반한다. daily digest에서도 같은 구조다.
- **근거:** 임시 DB에서 A에 URL 1, B에 URL 2만 기록하고 두 기사를 수집하도록 실행했다. 빌더에는 URL 1·2가 모두 전달됐고, 동일한 `batch.epub`이 A와 B 모두에 업로드됐다. 실행 후 양 기기에 양 URL 이력이 기록됐다.
- **반증 확인:** 업로드 자체는 미전송 기기만 대상으로 하며 성공 기기만 이력에 기록한다. 단일 기사 재시도와 모든 기기의 이력이 같은 경우에는 올바르다. 문제는 한 배치 안에서 기기별 누락 기사 집합이 다를 때만 발생하며, 현재 테스트는 “한 URL + 한 기기만 실패” 사례만 다룬다.
- **호출/영향 범위:** 전체 per-site 모드와 daily digest 모드. 선택 동기화는 사용자가 명시적으로 재선택할 수 있어 의미가 다르지만 동일한 공통 배치 로직을 사용한다.
- **권장 수정 방향:** 기기별 missing URL 집합을 먼저 계산하고, 동일 집합을 가진 기기끼리 그룹화해 그룹별 EPUB을 빌드·업로드한다. 최소한 자동 전체 동기화에서는 이미 전송된 기사를 해당 기기용 EPUB에서 제외해야 한다.
- **필요한 회귀 테스트:** A={1}, B={2}, 수집={1,2}에서 A용 EPUB은 {2}, B용 EPUB은 {1}이어야 한다. A={1}, B={}이면 A용은 {2}, B용은 {1,2}; 각 그룹의 성공 기기만 해당 URL 이력이 추가되어야 한다. per-site와 digest 모두 필요하다.

### [ISSUE-004] 특수문자 EPUB 파일명이 OPDS 카탈로그 XML을 깨뜨린다

- **위치:** `websync/servers/opds.py:89-123` `_serve_catalog`
- **우선순위:** Low
- **신뢰도:** Confirmed
- **문제:** `<title>`과 `<id>`에는 일부 escape한 `safe_name`을 쓰지만 `<summary>`의 `title`은 XML escape하지 않는다.
- **발생 조건:** OPDS output 폴더에 `A&B.epub`, `<` 등이 포함된 EPUB이 존재하고 카탈로그를 조회한다.
- **영향:** HTTP 200 응답이 well-formed XML이 아니어서 OPDS 클라이언트가 카탈로그 전체를 열지 못할 수 있다.
- **근거:** 임시 output에 `A&B.epub`을 만들고 실제 서버를 요청했다. `<summary>A&B.epub ...</summary>`가 생성되어 XML parser가 `invalid token`으로 실패했다.
- **반증 확인:** 앱이 생성하는 뉴스 EPUB 파일명은 영숫자·공백·`_`·`-`로 정리되므로 일반 생성 경로에서는 재현되지 않는다. 하지만 OPDS는 폴더의 모든 `.epub`을 열거하며 외부/수동 파일을 배제하지 않는다.
- **호출/영향 범위:** `GET /`, `/opds`, `/opds/` 카탈로그 전체. 파일 다운로드 경로의 traversal 방어와는 무관하다.
- **권장 수정 방향:** XML 문자열 수작업 연결 대신 XML builder를 쓰거나 모든 텍스트 노드와 속성을 `xml.sax.saxutils.escape/quoteattr`로 처리한다.
- **필요한 회귀 테스트:** `&`, `<`, `>`, 따옴표, 한글이 든 파일명을 함께 두고 `ElementTree.fromstring()`이 성공하며 각 download URL도 200인지 확인한다.

## 5. Potential Functional Gaps

- **Likely Gap — 앱 종료 시 직접 기기 작업:** `_on_close()`는 뉴스 파이프라인과 watch worker는 중단·대기하지만 Calibre 전송과 기기 파일 탭의 upload/download/delete/move/rename daemon thread는 등록하거나 기다리지 않는다. 작업 중 창을 닫으면 결과 확인 없이 프로세스가 종료되거나 Tk callback이 사라질 수 있다. 다운로드는 `.part` + `os.replace`로 로컬 파일을 보호하지만 기기 측 multipart 상태는 실제 펌웨어 검증이 필요하다.
- **Likely Gap — 공유 사이트 병합의 시각 기준:** `backup.format.now_iso()`와 `_sync_updated_at`도 timezone 정보 없는 로컬 시각이며 site/tombstone LWW는 문자열 비교다. 서로 다른 시간대 또는 시계가 어긋난 PC 사이에서 최신 사이트 수정·삭제 판정이 틀릴 수 있다. ISSUE-002와 같은 원인이지만 사이트 데이터에 대해서는 이번 감사에서 두 시간대 프로세스로 재현하지 않아 별도 버그로 확정하지 않았다.
- **Likely Gap — 일반 스크래퍼의 내부 주소 방어:** 선택자 도우미는 사설·loopback·link-local 주소를 검사하지만 공통 `fetch_url()`은 http(s)+host만 확인하고 redirect 후 최종 주소도 검사하지 않는다. 악성 피드/페이지가 상세 기사 요청을 내부 서비스로 redirect할 수 있다. 로컬 데스크톱 앱이고 사용자가 소스를 등록해야 하므로 즉시 High 보안 이슈로 올리지는 않았지만, 외부 콘텐츠에서 파생된 URL을 fetch하는 경로에는 동일한 정책이 필요하다.
- **Confirmed Gap — OPDS 임의 파일명 회귀 테스트:** 현재 테스트는 unicode 다운로드와 traversal은 다루지만 XML 메타문자 파일명의 카탈로그 유효성을 검사하지 않는다.
- **추정 — 실기기 중단 복구:** HTTP POST timeout 이후 기기 측에 부분 파일이 남는지, 같은 이름 재시도가 덮어쓰기인지 중복 생성인지는 펌웨어 계약이 없어 판단하지 못했다.
- **추정 — 외부 사이트 호환성:** 픽스처 테스트는 충실하지만 실제 웹사이트 DOM/API 변경은 이번 감사에서 네트워크 스모크를 실행하지 않았다.

## 6. Documentation Mismatches

| 문서 설명 | 실제 구현/확인 결과 | 판단 |
|---|---|---|
| README/README.ko: “Zero Duplicate Delivery”, “중복 전송 완벽 방지”, 새 기사만 전송 | 다중 기기 이력이 갈라지면 공통 EPUB 때문에 이미 받은 기사가 다시 포함됨 | ISSUE-003과 불일치 |
| USER_GUIDE: 이력 삭제 후 다시 동기화하면 재전송 가능 | 로컬 재전송 자체는 가능하지만 공유 폴더 사용 시 이전 tombstone이 최신 mark를 다시 지울 수 있음 | ISSUE-002 조건에서 불완전 |
| USER_GUIDE: OneDrive가 내려받는 중이면 다음 동기화 때 다시 시도 | push 시 부분/손상 JSON을 빈 원격으로 보고 즉시 덮어쓸 수 있음 | ISSUE-001과 불일치 |
| USER_GUIDE/DEVELOPER: 공유 폴더는 사이트·이력 정본을 병합 | 유효 JSON일 때는 맞지만 invalid/partial 상태를 보존하지 않음 | 오류 조건 설명 누락 |
| `AGENTS.md` 확인 지시 | 저장소 루트에 파일 없음 | 확인 불가로 명시 |

CLAUDE의 로드맵은 대부분 구현 완료된 초기 기록이라고 문서 자체가 명시한다. 이를 현재 미구현 기능 목록으로 오판하지 않았다. README의 13종 스크래퍼, 실행 명령, 선택 의존성, 저장 경로, i18n, 업데이트 서명 설명은 현재 코드와 대체로 일치한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. 공유 JSON의 “없음”과 “읽기 실패/부분 파일”을 구분하고, 후자의 push 덮어쓰기를 차단한다.
2. 이력·삭제 시각을 UTC aware 또는 epoch로 통일하고 legacy timestamp 정규화·마이그레이션을 구현한다.
3. 삭제 후 재전송 → 원격 union까지 포함한 통합 테스트를 추가한다.

### Phase 2 — Stability

1. 자동 전체 동기화에서 기기별 missing article set으로 EPUB 배치를 분리한다.
2. 앱 종료 시 Calibre 및 기기 파일 작업을 추적하여 완료 대기, 취소, 또는 명시적 종료 확인을 제공한다.
3. 공유 폴더 invalid JSON을 격리 보관하고 제한적 backoff/retry 및 사용자 경고를 추가한다.
4. 일반 scraper의 파생 URL과 redirect 최종 목적지에 내부 주소 정책을 적용하되, 의도적으로 로컬 사이트를 수집하는 사용 사례는 opt-in으로 분리한다.

### Phase 3 — Structural

1. 공유 데이터 포맷의 모든 시각 필드를 timezone-aware schema로 올리고 문자열 직접 비교를 제거한다.
2. `read_json_safe()` 대신 상태와 오류 원인을 반환하는 typed result를 사용한다.
3. OPDS XML을 표준 XML builder로 생성한다.
4. GUI의 모든 장기 작업을 하나의 작업 레지스트리에서 수명 주기·취소·종료 대기하도록 통합한다.

이 감사에서는 실제 코드를 수정하지 않았다.

## 8. Test Recommendations

### Unit

- `read_json_safe` 대체 API에 대해 missing, valid dict/list, empty, truncated UTF-8, malformed JSON, scalar JSON을 구분하고 예상 상태를 단언한다.
- timestamp parser에 SQLite UTC 공백형, `Z`, 양/음 offset, legacy naive 값을 넣고 동일 절대시간 정렬을 검증한다.
- 기기별 누락 집합 계산에 A={1}, B={2}, articles={1,2}를 넣어 `{A:{2}, B:{1}}`을 기대한다.
- OPDS filename `A&B.epub`, `<book>.epub`, 한글 파일을 XML로 만든 뒤 표준 parser로 검증한다.

### Integration

- 공유 폴더에 remote-only 사이트·이력을 둔 뒤 파일을 일시적으로 잘라낸 상태에서 push를 호출한다. push는 실패하고 원본/격리 사본이 보존되어야 한다.
- `mark → backup push → delete → backup push → resend → remote union → push` 전체 흐름 후 최신 이력이 로컬·원격 모두 남아야 한다.
- 두 기기의 분기 이력으로 per-site와 digest를 실행하고, 생성된 각 EPUB의 chapter URL 집합과 DB mark 집합을 비교한다.

### End-to-End

- 실제 X3/X4 두 대에서 한 기기 업로드만 의도적으로 실패시킨 뒤 재실행한다. 성공 기기에는 기존 기사가 포함된 새 책이 생기지 않고 실패 기기만 누락분을 받아야 한다.
- 실제 OneDrive 두 PC에서 한쪽 파일 다운로드 중 다른 쪽 자동 push를 실행해 기존 원격 정본이 보존되는지 확인한다.
- History 탭에서 삭제 후 즉시 재전송하고 두 번째 PC에서 pull해도 재전송 이력이 유지되는지 확인한다.

### Concurrency

- 두 프로세스가 같은 공유 폴더에 동시에 push할 때 한쪽이 invalid/partial 파일을 관측하면 둘 다 덮어쓰지 않고 재시도해야 한다.
- GUI 설정 저장과 background backup pull/push가 충돌할 때 sites, tombstone, portable metadata가 모두 보존되는지 검사한다.
- 뉴스 파이프라인·Calibre 전송·기기 파일 업로드 중 각각 앱 종료를 요청하고 문서화한 종료 정책대로 완료/취소되는지 확인한다.

### Regression

- 기존 부분 업로드 테스트를 한 URL뿐 아니라 서로 다른 두 URL/두 기기로 확장한다.
- 삭제 tombstone 테스트는 동일 시간대 문자열만 쓰지 말고 OS timezone과 UTC가 다른 환경을 강제한다.
- OPDS 테스트에서 HTTP 200뿐 아니라 XML well-formedness를 반드시 확인한다.
- 손상 공유 파일 테스트는 “None 반환”만 확인하지 말고 서비스 계층에서 overwrite가 금지되는지 단언한다.

### Platform-specific

- Windows/KST, Windows/UTC, Linux/UTC, macOS의 timestamp roundtrip을 CI matrix로 실행한다.
- Windows 경로 공백·한글, macOS launchd plist, Linux crontab의 실제 등록/해제 smoke를 격리 환경에서 확인한다.
- frozen EXE에서 `--smoke`, locale JSON, updater helper 교체/rollback을 Windows CI 산출물로 계속 검증한다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | **Needs Work** | 기본 단일 기기 흐름은 양호하나 다중 기기에서 중복 EPUB이 발생한다 |
| Runtime Stability | **Acceptable** | timeout, retry, 락, 원자 교체가 있으나 일부 GUI 장기 작업 종료 수명 주기가 분리되어 있다 |
| Data Integrity | **High Risk** | 공유 JSON 손상 덮어쓰기와 timestamp 혼용에 따른 최신 이력 제거를 재현했다 |
| Error Resilience | **Needs Work** | invalid remote JSON을 재시도 가능한 오류가 아니라 빈 상태로 취급한다 |
| Cross-platform Robustness | **Needs Work** | 코드·테스트는 다중 OS를 고려하지만 로컬 naive/UTC 혼용이 시간대별로 다른 오류를 만든다 |
| Test Confidence | **Acceptable** | 299개가 통과하고 핵심 경로 커버리지가 좋지만 손상 백업·시간대·분기된 다중 기기 이력이 빠져 있다 |

**실제로 먼저 수정할 문제 3개**

1. ISSUE-001 — 손상/부분 공유 JSON을 감지하면 push를 중단하고 원본을 보존할 것
2. ISSUE-002 — 이력과 tombstone의 시각 저장·비교를 UTC 절대시간으로 통일할 것
3. ISSUE-003 — 자동 동기화 EPUB을 기기별 누락 기사 집합으로 구성할 것

---

감사 중 저장소 코드는 수정하지 않았으며, 결과물은 이 문서뿐이다. 기존 사용자 작업 파일 `docs/RECOMMENDED_SCRAPING_SOURCES.md`는 변경하지 않았다.
