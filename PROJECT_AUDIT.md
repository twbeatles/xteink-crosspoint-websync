# Project Audit

> 후속 개선: 2026-10-15 현재 구현 진행 중. Phase 1의 설정 입력 검증·명시적 복구·전송 파일명 충돌 방지 수정을 확인했다. 전체 검증에서는 589개 통과·1개 건너뜀 외에 이 문서의 후속 개선 표식 누락 검사 1개가 실패했으며, 아래 감사 당시 발견 사항은 원래 기록으로 유지한다. 모든 개선이 완료된 상태는 아니다.

> 감사일: 2026-10-15 (Asia/Seoul) · 기준: `main`, `78ab38400d13dc46b0554ed320b44265c90b7a3f`
>
> 기능 구현·런타임 안정성 감사. 애플리케이션·테스트 코드 변경 없이 이 보고서만 갱신했다. 아래 이슈 번호는 이번 감사에 한정한다. 2026-10-13 감사의 같은 번호 및 후속 수정 이력은 [이전 구현 기록](docs/AUDIT_IMPLEMENTATION.md)을 참조한다.

## 1. Executive Summary

프로젝트의 주요 기능은 실제 production 경로에 연결되어 있으며, 테스트와 안정성 방어도 상당히 갖춰져 있다. 전체/선택 동기화, 미리보기, EPUB 생성, 다중 기기별 중복 제거, 공유 폴더 병합, Calibre/Watch, 파일 관리, OPDS·대시보드 및 서명 업데이트를 확인했다.

**전체 상태는 Needs Work, 전체 위험도는 Medium이다.** 특정 입력에서 재실행을 막는 설정 오염과 전송 파일명 충돌은 High로 분류한다. Critical 결함이나 SQLite 자체의 광범위한 손상은 확인하지 않았다.

| 중요한 문제 | 심각도 / 신뢰도 | 확인된 결과 |
|---|---|---|
| ISSUE-001: 잘못된 사이트 JSON을 저장한 뒤 검증 예외 발생 | High / Confirmed | `name: null` 가져오기 실패 후에도 잘못된 항목이 디스크에 남고, 새 ConfigManager에서도 로드 실패 |
| ISSUE-002: 로마자 변환 이후 해시 계산으로 원본 파일명이 충돌 | High / Confirmed | `가.epub`과 `ga.epub`이 모두 `ga_32d750.epub`으로 변환 |
| ISSUE-003: 같은 이름의 소스가 일간 합본에서 앞 소스를 대체 | Medium / Confirmed | 서로 다른 URL의 소스 두 개를 수집하지만 합본·이력에는 뒤 소스만 포함하고 성공 반환 |

데이터 손상·유실 가능성은 구분해야 한다. ISSUE-001은 JSON 문법 손상이 아니라 앱이 읽을 수 없는 의미적 설정 오염이다. ISSUE-002는 서로 다른 책의 원격 경로가 같아져, 같은 경로 업로드를 덮어쓰는 펌웨어에서는 이전 책이 대체될 수 있다. 실제 기기에서의 덮어쓰기 동작은 이번에 검증하지 않았다. ISSUE-003은 수집 결과 누락이며 누락한 기사를 완료 이력에 잘못 기록하지는 않는다.

가장 먼저 외부 JSON의 **저장 전 검증**을 고치고, 전송 파일명에서 **원본 식별성을 보존**해야 한다. 이어 합본의 소스 식별자를 표시 이름과 분리해야 한다.

## 2. Project Understanding

### 목적과 실행 방식

CrossPoint 펌웨어를 사용하는 XTEINK X3/X4의 데스크톱 동반 앱이다. 웹·RSS·블로그·뉴스레터·영상 자막을 EPUB으로 만들고 HTTP로 전송한다. 이미 전송한 URL은 기기별 SQLite 이력으로 제외한다. Calibre 서재와 로컬 전자책 전송도 제공한다.

README.md, CLAUDE.md, 제공된 AGENTS.md 및 디스크의 AGENTS.md를 확인했다. 개발 원칙은 역할별 모듈 분리·타입 힌트이며, 저장소 작업은 별도 지시가 없으면 main에서 수행한다. 이번에는 브랜치 전환·코드 수정·커밋·push를 하지 않았다.

### 주요 entrypoint와 핵심 모듈

| 진입점/모듈 | 역할 및 실행 경계 |
|---|---|
| `x3_websync.py:47 main` | GUI/`--sync`/`--smoke`/`--check-update`/업데이트 헬퍼 분기, GUI 단일 인스턴스 락 |
| `pipeline/service.py` | 설정 재로드, 작업 수락·취소·스레드/프로세스 락, 백업 pull/push 및 결과 상태 |
| `pipeline/sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py` | 전체 수집·선택 전송·미리보기·파일만 생성 |
| `scrapers/factory.py`, `scrapers/base.py` 및 전용 scraper | 타입별 수집, URL·limit 제한, HTTP GET retry·본문 크기 제한 |
| `epub/builder.py`, `sanitize.py`, `images.py` | 사이트별/합본 EPUB, 본문 정제, 오프라인 이미지 포함 |
| `upload/uploader.py`, `device_client.py` | 대상 기기별 전송, 파일 탐색·다운로드·삭제·이름/위치 변경 |
| `config/manager.py`, `validator.py`, `db/history.py` | 설정 RMW·revision 검사, 입력 검사, 기기별 전송 이력·삭제 표식 |
| `backup/service.py`, `format.py`, `replicas.py` | 공유 JSON 검증·병합, 기기 ID 조정, 설치별 복제본을 통한 사후 수렴 |
| `gui/app_core/`, `gui/settings_tab/watch.py`, `watch/calibre.py` | UI 비동기 작업·종료 대기, 파일 감시 및 pending_files 보존 |
| `servers/opds.py`, `servers/dashboard/` | EPUB 카탈로그, 인증된 상태·로그·동기화·취소 API |
| `scheduler/manager.py`, `integrations/calibre.py`, `core/update/` | OS 스케줄러, Calibre CLI, 서명·크기·해시 검증 및 업데이트 롤백 |

파일 경로는 표에서 `websync/` 접두사를 생략했다.

### 저장 방식과 외부 의존성

- 설정: UTF-8 `config.json`. 설정 락과 고유 임시 파일, fsync, `.bak`, `os.replace`, revision CAS/RMW를 사용한다.
- 이력: `sync_history.db`. `(url, device_ip)` 복합 PK, 작업별 연결·commit/rollback, 스레드 락 및 SQLite timeout이 있다. 레거시 스키마·`*` 이력 이관, 삭제 tombstone을 지원한다.
- 생성물/진단: `output/*.epub`, `logs/`, 파이프라인 락 파일. 개발 시 프로젝트 루트, frozen 시 EXE 폴더를 기준으로 하며 `X3_WEBSYNC_STORAGE_ROOT`로 저장 루트를 지정할 수 있다.
- 공유 폴더: `sites.json`, `synced_posts.json`, manifest 및 `.websync-replicas/*.json`. 기기 ID/alias와 삭제 표식도 병합한다. 로컬 클라우드 폴더의 락은 PC 간 분산 전송 락이 아니다.
- 필수 의존성: requests, BeautifulSoup, lxml, ebooklib, CustomTkinter, cryptography. pytest도 requirements.txt에 포함된다. 선택 기능은 Pillow, googletrans, youtube-transcript-api, watchdog 및 외부 Calibre에 의존한다.
- `x3_websync.spec`는 locale/template/theme 리소스와 hiddenimports를 포함한다. 경량 EXE는 Pillow·자막·Watch·googletrans 패키지를 제외하며 README FAQ가 이 제한을 설명한다.
- 일반 CI는 Linux/Python 3.15 전체 테스트와 Windows/Python 3.10 계약 테스트다. Windows/Python 3.15 frozen 빌드·smoke·서명 manifest 게시 등은 release.yml에 있다. 이 설명은 로컬 workflow 파일 기준이며 원격 CI를 이번에 조회하지 않았다.

### 핵심 사용자 흐름

1. **전체 동기화**: `main / GUI / Dashboard → SyncService 작업 수락·락 → 백업 pull → 설정 snapshot → ScraperFactory.fetch_articles → URL별 기기 이력 검사 → 번역/요약 → 미전송 기사 집합별 EPUB → HTTP 업로드 → 성공 기기만 mark_synced_many → 백업 push → bool·상태·로그·알림`.
2. **미리보기와 선택 전송**: `GUI → preview_articles → 공통 락·pull·수집·중복 검사 → 기사 목록 → sync_selected_articles → 최신 이력 재판정·기기별 배치 → EPUB/API/DB → 결과`. 미리보기는 전송 완료를 기록하지 않는다.
3. **EPUB만 생성**: `선택 기사 → 공통 파이프라인 락 → 현재 EPUB 설정 → build/build_digest → 파일 경로·결과`. 기기 업로드·완료 이력 기록은 없다.
4. **공유 데이터**: `설정·수동 요청·전송 전후 → BackupSyncService → 폴더 락·JSON/replica 확인 → URL/시간/삭제 표식 병합 → config RMW / DB union → 원자적 공유 파일 게시`. pull 실패 시 전송 중단, push 실패도 작업 실패로 보고하는 경로가 있다.
5. **Calibre/Watch**: `서재 조회 CLI 또는 파일 이벤트 → 선택/안정 크기 확인 → pending_files → 직렬 worker·파이프라인 락 → uploader → 결과·성공 시 pending 해제`.
6. **기기 파일 관리**: `선택 기기·원격 경로·로컬 파일 → GUI 확인/경로 정규화 → DeviceClient HTTP → 오류 변환·목록 새로고침`. 다운로드는 임시 파일을 거쳐 최종 파일을 교체한다.
7. **종료/업데이트**: `종료 → 새 작업 거부·취소 → 서버/Watch 정지 → 자기 worker·이력 commit 대기 → 백업 flush → Tk destroy`. 업데이트는 manifest 서명 → artifact 크기·SHA256 → 헬퍼 교체 → smoke → 실패 시 롤백 경로를 갖는다.

## 3. Audit Coverage & Limitations

### 실제 확인한 범위

위 모듈의 production 진입점과 주요 상태 변경 지점을 CodeGraph MCP로 우선 분석했다. 특히 다음 caller/callee 연결 및 소스를 확인했다.

- `main → SyncService → run_sync_pipeline_locked → build/build_digest → upload_to_targets → mark_synced_many`.
- `preview GUI → preview_articles`, `선택 GUI → sync_selected_articles/build_selected_epubs` 및 공통 락 수명.
- `import_sites → update_config → _save_config_unlocked → log_validation_warnings → validate_site`와 재기동 `main → load_config`.
- `upload/upload_to_targets/DeviceClient.upload_to_path → _sanitize_filename → romanize_for_filename`.
- `일간 합본 수집 → digest_articles → 기기별 배치 → build_digest` 및 GUI `save_site`의 이름/URL 검증.
- 공유 폴더 pull/push·replica 병합, SQLite migration·transaction·삭제 이력, Watch worker, GUI 종료, OPDS 경로·인증, 대시보드 작업 수락·취소 및 updater 검증/롤백.

도구가 생략한 본문은 함수명을 지정한 후속 CodeGraph 질의로 보완했다. 문서·설정·빌드·테스트 파일은 직접 읽었고 테스트 파일 목록은 `rg --files tests`로 확인했다. `scripts/migrate_to_package.py` 같은 개발용 migration script를 사용자 실행 경로의 위험으로 분류하지 않았다.

### 실행한 검증

환경: **Windows / Python 3.15.0**.

```text
python -B -m pytest tests/ -q --tb=short -ra -p no:cacheprovider
538 passed, 1 skipped in 103.32s (0:01:43)
exit code: 0
skip: tests/test_storage_isolation.py:121 — POSIX directory descriptors
```

전체 suite에는 DB·config concurrency, multi-PC 이력, 실제 loopback HTTP 계약, EPUB 구조/이미지, scraper fixture, pipeline failure recovery, GUI lifecycle, scheduler/Calibre adapter, updater 등의 테스트가 포함된다. 통과를 실기기·native GUI 전체 E2E 통과로 해석하지 않는다. 실행 중 일부 로컬 HTTP 요청 처리의 예외 배너가 출력됐지만 pytest 실패나 최종 경고 요약은 없었다. 배너만으로 별도 결함을 확정하지 않았다.

추가로 저장소에 테스트 파일을 추가하지 않고 일회성 Python을 실행했다. import 전에 임시 `X3_WEBSYNC_STORAGE_ROOT`를 지정하고 임시 config/DB/EPUB만 사용했다.

| 추가 재현 | 실제 결과 |
|---|---|
| `가.epub`/`ga.epub` sanitize | 두 출력 모두 `ga_32d750.epub` |
| `name: null` JSON import → 새 manager load | import와 재로드 모두 AttributeError, 해당 URL의 `name: null`이 JSON에 남음 |
| 이름 `same`, URL `/a`·`/b`, 서로 다른 기사로 전체 daily_digest 실행 | 성공 True, 합본에 BODY-a 없음/BODY-b 있음, 완료 이력 1건 |
| 같은 날 build_digest 두 번 실행 | 서로 다른 경로, 첫 파일 bytes 보존. 덮어쓰기 의심 반증 |

합본 재현은 실제 ConfigManager·SyncService·SQLite·EPUB ZIP을 사용했으며 수집기와 업로드 결과 및 알림은 stub/mock으로 대체했다. 파일명 재현은 변환 함수 경계까지다. 실제 기기 요청·알림·스케줄 등록은 실행하지 않았다.

### 한계

- CodeGraph는 AST·이름 기반 구조 분석이며 동적 호출 연결은 best effort다. 반환된 source와 실제 테스트를 함께 판단했다. 저장소 전 파일·전 분기를 완전 검증하지 않았다.
- 실제 X3/X4, CrossPoint 버전별 API 의미·덮어쓰기·한글 표시·배터리/절전 상태를 확인하지 못했다.
- 실제 외부 사이트·YouTube·AI/번역 provider·Calibre 서재·OneDrive/Dropbox/Google Drive를 대상으로 작업하지 않았다. 최신 외부 API 호환성을 보장하지 않는다.
- macOS/Linux native GUI·scheduler·notification 및 이번 commit의 원격 CI 결과는 미확인이다. frozen EXE 빌드·실행, 실제 브라우저 login/start/cancel/polling도 이번에는 수행하지 않았다.
- 기존 테스트의 임시 저장 경로·I/O guard를 확인하고 사용했다. 이는 OS sandbox가 아니다. 사용자 config/DB 내용을 열어보거나 복구·수정하지 않았고 의존성을 설치하지 않았다.

## 4. High-Risk Issues

이 절에는 반증 후 남은 Confirmed만 기록한다. Medium 항목도 기능 위험으로 함께 수록하되 심각도를 구분한다.

### [ISSUE-001] 잘못된 사이트 가져오기가 설정을 영구 저장한 후 실패하여 다음 기동도 막음

- **위치:** `websync/config/manager.py:444 import_sites`, `:351 update_config`, `:300 load_config`; `websync/config/validator.py:86 validate_site`.
- **우선순위:** High.
- **신뢰도:** Confirmed.
- **문제:** 가져오기에서 객체/배열과 URL만 제한적으로 확인한 뒤 사이트 필드를 저장한다. `update_config`는 저장 후 `log_validation_warnings`를 호출한다. validator는 `name`이 문자열이라고 가정해 `.strip()`을 호출하므로 null 입력에서 예외가 난다. 실패 반환 시 이미 저장한 내용은 롤백되지 않는다.
- **발생 조건:** 사용자 사이트 가져오기 JSON에 `{"sites":[{"name":null,"type":"rss","url":"https://example.test/feed"}]}`가 들어 있다. 정상적인 앱 export만 사용하면 발생하지 않지만, 수동 편집·다른 도구에서 만든 JSON을 읽는 공개 사용자 기능이다.
- **영향:** 가져오기가 실패했다고 표시돼도 로컬 설정에 잘못된 사이트가 남는다. 이후 ConfigManager.load_config가 같은 validator에서 실패해 GUI와 `--sync` 초기화가 막힌다. 수동 설정 수정/백업 복구가 필요하다. JSON 문법·기존 사이트 전체가 소실된다는 의미는 아니다.
- **근거:** `import_sites:466–474`는 기본값 병합만 하고 `:510`에서 update_config를 호출한다. `update_config:360`의 저장 다음 `:361`에서 validator를 실행한다. `validate_site:90`은 `site.get("name", "").strip()`이다. 임시 파일 재현에서 import와 새로운 manager의 load 모두 `'NoneType' object has no attribute 'strip'`를 발생시켰고, 해당 URL의 원시 JSON name은 None이었다.
- **반증 확인:** GUI 직접 입력 폼은 빈 이름 등을 검사하지만 파일 가져오기는 그 폼을 경유하지 않는다. deep merge는 존재하는 null을 기본 문자열로 바꾸지 않는다. 프로세스 락·revision·fsync·원자 교체는 동시성/파일 쓰기를 보호할 뿐 잘못된 값을 거부하지 않는다. `.bak`은 있으나 load에서 자동 fallback하지 않는다. GUI 오류 표시와 main의 초기화 예외 처리는 장애를 알리지만 저장 상태를 되돌리지 못한다.
- **호출/영향 범위:** CodeGraph `SyncSitesMixin._import_sites_action → ConfigManager.import_sites → update_config → _save_config_unlocked → log_validation_warnings`; 이후 `main → ConfigManager.load_config → validate_site`. 같은 validator를 쓰는 다른 외부 설정 입력도 타입 방어가 필요하지만, 이번 확정 재현은 사이트 import다.
- **권장 수정 방향:** 저장 전에 import의 필드 타입·값·전체 설정을 검사하고 실패하면 기존 파일과 revision을 유지한다. validator는 null/숫자/list를 오류 목록으로 변환하고 예외를 내지 않도록 한다. `.bak` 복구는 명시적 사용자 복구 경로와 함께 설계한다.
- **필요한 회귀 테스트:** 정상 config bytes/revision을 저장한 뒤 위 JSON을 import하면 ConfigLoadError 등 명확한 입력 오류가 나고 원본 bytes/revision이 유지되어야 한다. 이어 새 manager의 load와 서비스 초기화가 성공해야 한다. name/url/선택자 필드에 null·숫자·배열을 각각 적용한다.

### [ISSUE-002] 로마자 변환 뒤 해시를 계산하여 서로 다른 원본 전송 파일명이 같아짐

- **위치:** `websync/upload/uploader.py:42 X3Uploader._sanitize_filename`, `websync/upload/romanize.py:71 romanize_for_filename`.
- **우선순위:** High.
- **신뢰도:** Confirmed — 결정적 파일명 충돌을 재현했다. 실제 기기의 덮어쓰기 결과는 미검증이다.
- **문제:** 원래 basename을 로마자로 바꾼 뒤 그 결과에 MD5를 적용한다. 로마자 표기는 일대일 변환이 아니므로 해시가 원본 간 차이를 보존하지 못한다. 짧은 해시의 우연한 충돌 문제가 아니라 동일한 해시 입력을 만드는 구조적 충돌이다.
- **발생 조건:** `가.epub`과 `ga.epub`, 또는 같은 로마자 표기로 변환되는 서로 다른 제목을 같은 원격 폴더로 보낸다. 날짜가 붙은 사이트별 생성물에서도 날짜가 같으면 발생할 수 있다.
- **영향:** 서로 다른 책이 같은 원격 파일을 가리킨다. 동일 경로 업로드를 대체하는 펌웨어에서는 앞 책을 잃을 수 있으며, 기사 동기화에서는 두 업로드가 성공하면 각각의 완료 이력이 남아 앞 기사도 재전송 대상에서 제외될 수 있다. 실제 기기가 중복을 거부한다면 덮어쓰기 대신 전송 실패로 나타난다.
- **근거:** `uploader.py:44–47`에서 `base = romanize_for_filename(base)` 다음 해시를 계산한다. 실제 함수 호출 결과는 `가.epub → ga_32d750.epub`, `ga.epub → ga_32d750.epub`였다. 서로 다른 원본을 구분한다는 주석·문서 계약을 만족하지 않는다.
- **반증 확인:** ASCII filtering 뒤 suffix가 붙어도 이미 동일한 입력의 해시라 차이가 생기지 않는다. builder의 파일 존재 검사/시간 suffix는 서로 다른 원래 이름의 로컬 파일 사이에는 적용되지 않는다. 기기 파일 탭의 overwrite 확인은 일부 수동 경로에만 있으며, 한 번에 선택한 두 로컬 파일끼리의 충돌은 업로드 전 원격 조회만으로 막지 못한다. 전체/선택 동기화·Calibre/Watch 업로드에는 동일한 확인이 항상 적용되지 않는다.
- **호출/영향 범위:** CodeGraph `_sanitize_filename ← upload / upload_to_targets`, `DeviceClient.upload_to_path`도 같은 함수를 사용한다. 전체/선택 파이프라인, Calibre/Watch, 수동 파일 전송에 공통 영향이다.
- **권장 수정 방향:** 변환 전 원래 basename을 별도 보존해 그 값으로 해시를 계산하고, 사람이 읽는 prefix에만 로마자 변환을 적용한다. 전송 배치에서 동일 원격 이름도 검사한다. 기존 기기 파일과의 호환/이름 변경 정책은 명시한다.
- **필요한 회귀 테스트:** `가.epub`/`ga.epub`, 서로 다른 받침이 같은 표기로 변환되는 한글 쌍, 악센트 포함/미포함 이름을 넣어 ASCII·확장자·날짜 보존과 서로 다른 출력 이름을 확인한다. fake CrossPoint에 두 책을 전송했을 때 서로 다른 key와 bytes로 둘 다 남아야 한다.

### [ISSUE-003] 표시 이름이 같은 소스가 일간 합본에서 앞 소스 기사를 조용히 누락

- **위치:** `websync/pipeline/sync_pipeline.py:180–183 run_sync_pipeline_locked`; 입력 허용 경로 `websync/gui/sync_tab/site_dialog.py:405 save_site`.
- **우선순위:** Medium.
- **신뢰도:** Confirmed.
- **문제:** 일간 합본의 누적 dict를 사이트 표시 이름으로 인덱싱하고 `digest_articles[name] = new_articles`로 대입한다. 다른 URL의 소스가 같은 이름이면 이전 목록이 교체된다. 이름의 유일성은 입력 계약으로 강제되지 않는다.
- **발생 조건:** 켜진 소스 두 개가 같은 이름이고 서로 다른 URL이며, 둘 다 새 기사가 있고 `epub_merge_mode=daily_digest`인 전체 동기화를 실행한다.
- **영향:** 앞 소스 기사를 가져왔다는 로그는 나오지만 생성/전송한 합본에서는 빠진다. 뒤 소스만 전송하고 작업은 성공한다. 앞 기사 완료 이력은 기록하지 않으므로 재시도가 가능하지만, 계속 두 소스에 새 글이 있으면 누락이 반복될 수 있다.
- **근거:** 임시 설정에 이름 `same`, URL `https://example.test/a` 및 `/b`, 기사 BODY-a/BODY-b를 넣었다. 실제 서비스·DB·EPUB 실행에서 반환값 True, ZIP XHTML에 BODY-a 없음/BODY-b 있음, DB 고유 URL 1건을 확인했다. builder의 파일명 문제가 아니라 builder에 들어가기 전 누적 결과 문제다.
- **반증 확인:** GUI는 이름 공백, URL scheme, limit, CSS 문법 및 중복 URL 확인을 제공한다. 서로 다른 URL의 같은 이름은 막지 않는다. config validator도 이름 유일성을 검사하지 않는다. DB PK·중복 필터는 서로 다른 기사 URL에 대한 것이므로 합본 dict의 덮어쓰기를 막지 못한다. 선택 전송의 `setdefault(...).append(...)`는 이 누락을 피하지만 전체 동기화는 그 경로를 쓰지 않는다.
- **호출/영향 범위:** CodeGraph `main/GUI/Dashboard → SyncService.run_sync_pipeline → run_sync_pipeline_locked → digest_articles → group_articles_by_pending_targets → build_digest`. 전체 일간 합본에 한정한 확정 문제다. 선택 전송에서는 같은 이름의 번역 설정 구분이 모호할 수 있으나 별도 결함으로 확정하지 않았다.
- **권장 수정 방향:** 소스 URL/안정 ID로 누적하고 표시 이름은 레이블로만 사용한다. 최소 수정은 같은 이름의 목록을 append/extend하여 기사를 보존하는 것이지만 소스별 옵션도 구별할 수 있어야 한다.
- **필요한 회귀 테스트:** 같은 이름·다른 URL·서로 다른 기사 두 개로 전체 합본을 실행해 ZIP에 두 본문, DB에 두 URL, 성공 결과를 확인한다. 두 번째 실행은 신규 없음이어야 한다. 기기별 미전송 기사 집합이 다른 경우에도 모든 대상의 합본에 필요한 기사만 남아야 한다.

## 5. Potential Functional Gaps

이 절은 현재 버그와 기능 확장/운영 제약을 구분한다.

| 구분 | 보완점 | 판단 및 기대 동작 |
|---|---|---|
| Confirmed Gap | 설정 오류 복구 UX | `.bak`/`.corrupt` 보존은 있으나 읽기 실패 후 앱 안에서 정상본 선택·복구하는 기동 경로는 확인되지 않았다. ISSUE-001 수정과 함께 유용하지만 자동 복구 부재 자체를 데이터 파괴로 분류하지 않는다. |
| Confirmed Gap | PC 간 정확히 한 번 전송 | 공유 폴더의 로컬 락/replica는 분산 전송 lease가 아니다. README와 구현 기록도 같은 reader의 자동 전송 PC를 하나로 제한한다. 동시/offline 전송까지 요구한다면 서버 CAS/lease가 필요한 추가 기능이다. |
| Confirmed Gap | 응답 유실 뒤 원격 완료 조정 | HTTP 성공 후 로컬 DB commit 전 강제 종료, 또는 기기 완료 후 응답 유실은 재전송될 수 있다. 기존 문서에 공개한 제약이다. 원격 파일/hash 조회나 idempotency 지원이 있어야 완료 여부를 안전하게 조정할 수 있다. |
| Likely Gap | Watch 실패 항목의 실행 중 재시도 | pending_files 보존과 시작 시 재큐잉은 있으나 `_upload_worker` 실패 항목을 현재 실행 중 다시 처리하는 주기적 retry는 확인하지 못했다. 자동 retry가 필요하다면 backoff·부분 성공 기기 상태·중복 큐 정책을 정해야 한다. 현재는 재시작 등의 복구가 가능한 제약이다. |
| 추정 | 원격 서비스의 장기 호환성 | fixture와 adapter 계약은 외부 HTML/API 변경을 탐지하지 못할 수 있다. opt-in live smoke를 별도 환경에서 운영할 가치가 있다. 이번에 실제 서비스 장애를 관측한 것은 아니다. |

## 6. Documentation Mismatches

1. **원래 basename hash 설명과 구현 불일치:** README 마지막 Reliability 항목, CLAUDE/AGENTS 후속 안정성 기록, `docs/AUDIT_IMPLEMENTATION.md`는 원본 이름 hash로 고유성을 보존한다고 설명한다. 실제로는 로마자 변환 후 hash이므로 ISSUE-002 재현과 모순된다.
2. **개발 문서의 과거 구조 설명:** CLAUDE/AGENTS 본문은 `uploader.py`를 영숫자 필터링 중심으로 설명하고 네이버 이미지를 항상 제거한다고 설명한다. 실제 uploader는 `romanize.py`를 사용하고 현재 이미지 정책은 include_images에 따라 달라진다. 후속 기록은 일부를 바로잡지만 본문과 함께 읽으면 혼동된다. 초기 로드맵은 역사 기록이라고 명시하므로 구현 누락 목록으로 취급하지 않았다.
3. **오래된 선택 의존성 주석:** requirements.txt의 주석은 `googletrans==4.0.0-rc1`을 안내하지만 실제 requirements-optional.txt와 adapter 계약은 `>=4.0.2,<5`다. 설치 가능한 공식 목록을 하나로 맞춰야 한다. 해당 주석을 따른 구버전 호환 실패는 이번에 별도로 재현하지 않았다.

README FAQ의 경량 EXE 선택 기능 제외, 클라우드 분산 락 한계, 후속 문서의 과거 CI와 현재 2-job CI 구분은 실제 설정과 부합한다. 이를 불일치/미구현 버그로 분류하지 않았다. 과거 구현 기록에 적힌 테스트 수·릴리즈 정보는 당시 기록이며 이번 테스트 결과나 최신 원격 상태로 재사용하지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. ISSUE-001: 외부 JSON 저장 전 타입/의미 검증, 실패 시 원본 유지, 재기동 정상성 회귀. 가져오기 오류가 기존 설정을 오염시키지 않는 것을 완료 조건으로 한다.
2. ISSUE-002: 원본 basename으로 해시 계산, 로마자 prefix는 표시용으로 유지, 배치 내 충돌 검사. 기존 전송 파일명과의 전환 정책을 정한다.

### Phase 2 — Stability

1. ISSUE-003: 전체 합본 소스 누적 키 수정, 두 본문·기기별 이력까지 통합 회귀.
2. config validator를 타입 안전하게 만들고 import·백업·기동 경계에서 공유한다. 저장 후 예외는 성공/실패 표시와 디스크 상태가 어긋나지 않게 처리한다.
3. Watch pending 재시도 요구를 결정하고, 필요하면 backoff와 기기별 부분 실패 추적을 설계한다.
4. 실기기 전송 충돌·완료 의미, 실제 클라우드 복제 지연, native OS scheduler 및 frozen 실행을 별도 검증한다.

### Phase 3 — Structural

1. 소스의 stable ID/URL과 사용자 표시 이름을 데이터 모델에서 구분해 합본·번역 옵션·프리뷰 선택에 일관되게 전달한다.
2. 검증 실패를 문자열 문구 판별보다 구조화된 필드/코드로 전달하도록 정리해 GUI와 파일 입력이 같은 계약을 사용하게 한다.
3. fixture·loopback 테스트와 opt-in 외부/native 검증을 분리하고 보고서에 실제 보장 범위를 계속 명시한다. 기능 영향 없는 이름·스타일 변경은 계획에서 제외한다.

위 내용은 수정 권고이며 실제 코드는 변경하지 않았다.

## 8. Test Recommendations

| 계층 | 입력 조건/실행 | 기대 결과 |
|---|---|---|
| Unit — ISSUE-001 | name/url/CSS 필드에 null·숫자·배열, sites에 잘못된 구조를 validator에 전달 | 예외 대신 필드별 오류 목록. 정상 필드는 그대로 유지 |
| Integration — ISSUE-001 | 정상 config와 revision을 저장하고 `name:null` 사이트 파일 import | 입력 오류 반환, config bytes/revision 불변, 새 manager load 성공 |
| Regression — ISSUE-001 | 정상 사이트 1개와 잘못된 사이트 1개가 섞인 import | 정의된 all-or-nothing 계약에 따라 전체 거부, 정상 설정·백업 보존. 실패 뒤 부분 저장 없음 |
| Unit — ISSUE-002 | `가.epub`/`ga.epub`, 서로 다른 한글 동음 표기, 악센트/ASCII 쌍 | 출력은 ASCII·정상 확장자이며 원본이 다르면 서로 다른 이름 |
| Integration — ISSUE-002 | fake CrossPoint 같은 폴더에 서로 다른 payload 두 개 전송 | 두 원격 key와 두 payload 보존. HTTP 성공과 DB 이력이 실제 파일에 대응 |
| End-to-End — ISSUE-003 | 같은 이름/다른 feed URL 두 개, 각각 새 기사, daily_digest | 수집→실제 EPUB ZIP→fake upload→실제 SQLite에서 두 기사 보존. 재실행 no_new |
| Regression — 기기별 중복 | A는 기사1 완료/B는 기사2 완료 상태에서 합본·선택 전송 | A에 기사2만/B에 기사1만 포함, 성공 기기만 기록. 실패 후 재시도에서 완료 기기 제외 |
| Concurrency — 설정 | 잘못된 import와 정상 사이트 편집을 barrier로 경합 | 잘못된 import는 디스크를 바꾸지 않고 정상 편집 유지, revision 일관성 유지 |
| Concurrency — 작업 수락 | GUI·CLI·Dashboard에서 같은 저장 루트로 동시 시작, 한 작업에 취소 | 수락 작업 1개, busy 요청이 기존 취소 상태를 지우지 않음, 락 해제 후 다음 작업 정상 실행 |
| Integration — 전송/DB 장애 | HTTP 완료 직후 DB commit 실패·worker 예외 | 성공을 추정 기록하지 않고 실패 상태, lock 해제. 응답 유실 시 중복 가능성은 공개 계약에 맞게 표시 |
| End-to-End — 종료 | 느린 업로드/Watch 대기 중 GUI close, 임시 DB 사용 | 새 작업 거부, Tk 이벤트 처리 유지, 완료 이력 commit·pending 보존·백업 flush 뒤 종료 |
| Integration — 공유 폴더 | canonical/replica의 빈 파일·잘린 JSON·타입 오류, 이전 snapshot의 tombstone | 실패 입력이 기존 config/DB를 오염시키지 않음. 유효한 복제본 수렴 뒤 삭제/재등록 관계 보존 |
| Unit/Integration — Watch | 첫 업로드 timeout 후 파일 변경 이벤트 없이 연결 복구 | 현행 재시작 복구 계약 또는 새 자동 retry 계약에 따라 pending이 정확히 한 번 재큐잉되고 성공 후 제거 |
| Platform-specific — Windows | 공백/한글 설치 경로, 실제 schtasks와 frozen EXE, 표준 사용자 권한 | 등록한 명령의 cwd·인터프리터 정확, 임시 저장 루트에서 smoke 성공, 사용자 데이터 불변 |
| Platform-specific — Linux/macOS | disposable 환경에서 cron/launchd 등록·해제·실행과 GUI close | 사용자 기존 일정 보존, UTF-8 경로/환경 정상, 작업 종료와 락 해제 확인 |
| Native/Device E2E | 실제 X3/X4에서 파일명 충돌 쌍·같은 날 여러 합본·오프라인 이미지 | 서로 다른 책 보존, 본문·TOC·이미지 정상 표시, firmware API 완료/대체 의미 기록 |
| Browser E2E | 임시 서비스에서 login→sync→status/log polling→cancel, 401/409/응답 유실 | 인증·중복 작업 거절·취소 상태 반영, 불확실한 mutation 자동 재시도 없음 |

기존 `test_uploader_sanitize.py`는 서로 다른 한글 이름을 검사하지만 동일 로마자 결과 쌍은 검사하지 않는다. `test_pipeline_digest.py`의 다중 사이트 테스트는 서로 다른 이름을 사용하고 builder를 mock하므로 같은 이름의 실제 EPUB 누락을 놓친다. Watch의 이동 이벤트 테스트는 자체 helper로 handler 로직을 재현하므로 실제 등록된 watchdog handler와의 연결 검증을 보완할 가치가 있다. 전체 통과가 이 경계 입력을 이미 검사했다는 뜻은 아니다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Needs Work | 정상 경로와 다중 기기 처리는 구현됐으나 같은 이름 합본 누락·파일명 충돌 재현 |
| Runtime Stability | Needs Work | 작업 락·종료 대기·예외 결과 처리는 양호하지만 import 한 번으로 다음 기동까지 실패 가능 |
| Data Integrity | Needs Work | SQLite PK/transaction·원자적 파일 쓰기는 유효. 의미적 config 오염과 원격 파일 식별성은 보완 필요 |
| Error Resilience | Needs Work | HTTP timeout/retry·백업 fail-closed·rollback 경로는 있으나 저장 후 검증 예외에서 상태 불일치 |
| Cross-platform Robustness | Acceptable | OS별 adapter·경로/락 계약과 Windows 전체 테스트가 존재. 이번 Linux/macOS native 검증은 없음 |
| Test Confidence | Acceptable | 538 passed/1 skipped, fixture·loopback·concurrency 범위가 넓음. 실제 외부/native E2E 및 새 경계 사례 공백 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 가져오기 저장 전에 검증해 잘못된 JSON이 다음 앱 실행을 막지 않게 한다.
2. **ISSUE-002:** 변환 전 원본 이름으로 해시를 계산해 서로 다른 책의 원격 파일명 충돌을 막는다.
3. **ISSUE-003:** 일간 합본에서 표시 이름이 같은 소스의 기사도 모두 보존한다.
