# Project Audit

감사일: 2026-09-22 (UTC)
기준: 작업트리 스냅샷 (9개 파일 미커밋 변경 + `tests/test_multi_pc_history.py` 미추적) / v1.2.2 / Windows + Python (소스 실행)
범위: 기능 구현, 런타임 안정성, 데이터 무결성, 오류 복구, 기능 관련 보안 경계. 스타일·네이밍·취향성 리팩터링은 제외.
방식: CodeGraph 호출관계 분석 + 핵심 모듈 직접 열람 + 반증 시도 + 전체 테스트 2회 실행 + 스모크 체크. **코드는 수정하지 않았다.**

> 이전 감사 스냅샷(2026-09-20, v1.2.1, 307 passed)의 remediation 4건(공유 JSON strict reader, tombstone 시각 비교, 기기별 배치, OPDS escape)은 본 감사에서 코드상 존재를 재확인했다. 본 문서는 그 문서를 대체하며, remediation 기록은 §5 말미에 요약 보존한다.

## 1. Executive Summary

프로젝트 전체 상태는 **양호하나 작업트리 상태가 감사 결론을 약화시킨다**. 핵심 단일·다중 기기 동기화 흐름(수집 → 중복 제거 → EPUB 빌드 → 성공 기기만 기록 → 업로드)은 견고하게 설계되어 있다. SQL/셸 인젝션·경로 탈출·원자적 저장·락 직렬화 등 과거 지적 경계는 코드 열람으로 방어 확인했다.

전체 위험도는 **Acceptable (조건부)** — 단, 감사 도중 작업트리가 실제로 변경되어 테스트 결과가 바뀌었다(아래). 제품 코드 자체보다 **미커밋·이동 중인 작업트리가 현재 가장 큰 리스크**다.

가장 중요한 문제 3~5개:

1. **[ISSUE-001] 감사 중 테스트 스위트가 적색→녹색으로 바뀜** (High, 관측 Confirmed). 1차 전체 실행에서 `1 failed, 307 passed` (종료코드 1), 이후 재실행에서 `310 passed`. 원인은 제품 버그가 아니라 감사 도중 변경된 작업트리(기기 alias-id 기능이 7개 미커밋 파일 + 미추적 테스트에 걸쳐 부분 착지). 릴리스 게이트의 결정성을 깨뜨린다.
2. **[ISSUE-002] `test_connection`이 HTTP 상태코드를 무시** (Medium, Confirmed). 404/500을 반환하는 무관한 웹서버도 "연결됨"으로 보고한다.
3. **[ISSUE-003] 선택 동기화·프리뷰가 취소 요청을 무시** (Medium, Likely). 전체 파이프라인과 달리 사이트 경계 취소 검사가 없어 종료 계약이 성립하지 않는다.
4. **[ISSUE-004] Linux crontab 등록/해제가 사용자 크론 줄을 함께 삭제** (Low, Confirmed). `script_path`가 포함된 무관한 줄까지 필터링한다.
5. **[ISSUE-005] `limit` 검증이 권고 수준이라 비정상값이 스크래퍼까지 도달** (Low, Confirmed). 음수 `limit`는 조용히 수집 개수를 바꾼다.

데이터 손상/유실 가능성: **로컬 파이프라인에서는 확인되지 않았다.** 업로드 실패를 성공으로 기록하는 경로는 없다(성공 IP만 `mark_synced_many`). 공유 폴더 덮어쓰기·시각 비교 문제는 이전 remediation이 코드에 존재한다. 확인된 유실 가능성은 ISSUE-004의 사용자 crontab 줄 삭제(복구 가능, 조건 협소)뿐이다.

가장 먼저 수정해야 할 영역: `upload/uploader.py`의 연결 판정, 선택/프리뷰 경로의 취소 처리, 그리고 무엇보다 **작업트리 정리(alias-id 변경 커밋 + 미추적 테스트 편입)와 클린 트리 게이트**.

## 2. Project Understanding

목적: Xteink X3/X4(CrossPoint 펌웨어) e-ink 리더기를 위한 뉴스·콘텐츠 수집 → EPUB 빌드 → Wi-Fi 무선 전송 자동화 데스크톱 앱(GUI + 헤드리스 `--sync`).

주요 entrypoint (`x3_websync.py:47-140`):

- `--smoke` → `core/smoke.run_smoke_check()` (import + i18n 검증, exit 0/1)
- `--apply-update*` → `cli/update_apply.handle_apply_update()` (부모 종료 대기 후 교체·재기동)
- `--check-update` → `UpdateService.check_for_update()` 출력 후 종료
- `--sync` → GUI 락 없이 `SyncService.run_sync_pipeline()` 후 exit 0/1
- 기본 → GUI 단일 인스턴스 락(`core/instance_lock.py`: Windows named mutex + 임시 락파일) 후 `SyncAppGui.run()`

핵심 모듈:

- `pipeline/service.py` — `SyncService` 파사드. 클래스 공유 `threading.Lock` + `ProcessFileLock` 비차단 획득(실패 시 즉시 False), `maybe_backup_pull → _run_sync_pipeline_locked → maybe_backup_push` 순서 보장.
- `pipeline/sync_pipeline.py` — 전체 동기화. 사이트별 try/except 격리, `article_sync_key`로 URL 키 정규화, `needs_sync` 필터, 번역/요약(실패해도 해당 사이트만 스킵, 다음 실행에 재시도), `group_articles_by_pending_targets`로 기기별 missing 집합이 같은 기기끼리만 묶어 별도 EPUB 빌드·전송·기록.
- `pipeline/selected_sync.py`, `pipeline/preview.py` — 동일 락 공유, preview는 빌드/업로드 생략.
- `db/history.py` — SQLite `(url, device_ip)` PK, `timeout=10.0`, WAL, 클래스 `_db_lock`, `_connect` 커밋/롤백, `mark_synced_many` 단일 트랜잭션 + tombstone 정리, `deleted_posts` tombstone 병합(`_time_key` 절대시간 비교).
- `upload/uploader.py` — 파일명 sanitize + md5 short hash, 크기 기반 타임아웃(25s + 5s/MB), `ThreadPoolExecutor(≤4)` 병렬 전송, `{ip: bool}` 반환, 호출당 `last_errors` 초기화.
- `upload/device_ids.py` — 안정 device id 우선 이력 키, `alias_keys`(id·IP·레거시 호스트), 미커밋 변경으로 `primary_alias_ids`/`alias_ids` 지원 추가 중.
- `config/manager.py` — 결손 키 deep-merge 보강, 토큰 자동생성, pid·tid·uuid tmp + fsync + `.bak` + `os.replace` 원자 저장, `_config_revision` CAS(`update_config`/`patch_fields`), 손상 JSON은 `.corrupt` 복사 후 `ConfigLoadError`.
- `epub/` — 테마/기본 CSS(폰트 allowlist·수치 clamp), 본문 sanitize(script/style/iframe/object/embed/form + `on*` + `javascript:` 제거), 표지(Pillow, 없으면 생략).
- `scrapers/` — 13종 팩토리 싱글턴, 공통 `fetch_url`(Retry 3회·본문 16MB 상한·리다이렉트 5회·공개 URL의 private/local 리다이렉트 차단), 계약 `{title, content, url}`.
- `servers/` — OPDS(인증 선택·basename + realpath + normcase containment·청크 전송), 웹 대시보드(토큰/Bearer·세션쿠키, `/api/sync` 이중 busy-check 후 `begin_sync_pipeline_async` 비차단 기동).
- `scheduler/manager.py` — schtasks/launchd/crontab, hour/minute 정수 whitelist, argv 실행(`shell=False`).
- `backup/` — 공유 폴더 JSON 정본 pull/push, 폴더 락, strict reader(손상 시 중단), 원자 쓰기.
- 외부 의존성: 필수 `requests/beautifulsoup4/lxml/ebooklib/customtkinter/cryptography`, 선택 `Pillow/googletrans/youtube-transcript-api/watchdog`.

핵심 실행 흐름:

```
[GUI --sync] x3_websync.py:main → SyncService.run_sync_pipeline (service.py:298)
  → _try_acquire_pipeline_locks (thread→process 순서, 실패 롤백)
  → _run_pipeline_body: maybe_backup_pull → run_sync_pipeline_locked → maybe_backup_push
  → per site: ScraperFactory.get_scraper.fetch_articles → article_sync_key로 url 덮어씀
    → db.needs_sync(url, history_keys, aliases) → translate → summarize
    → group_articles_by_pending_targets → EpubBuilder.build → uploader.upload_to_targets(only_ips)
    → collect_mark_entries(성공 IP만) → db.mark_synced_many → Result{status,success,…} + toast
```

## 3. Audit Coverage & Limitations

실제 확인한 주요 모듈(본문 직접 열람): `x3_websync.py`, `pipeline/service.py·sync_pipeline.py·selected_sync.py·preview.py·article_keys.py·upload_results.py·summarizer.py·translator.py`, `db/history.py` 전부, `upload/uploader.py·host.py·remote_path.py·device_ids.py·device_client.py(대부분)`, `config/manager.py` 전부 + `validator.py(limit 부분)`, `core/process_lock.py·instance_lock.py·paths.py·article.py·update/installer.py(부분)·cli/update_apply.py`, `scrapers/factory.py·base.py·rss.py(부분)·css.py(limit 부분)`, `epub/builder.py·css.py·sanitize.py`, `scheduler/manager.py` 전부, `servers/opds.py` 전부 + `dashboard/handler.py(대부분)·dashboard/service.py(부분)+settings_tab/servers.py(배선)`, `backup/service.py(부분)·atomic_io.py`, `integrations/calibre.py·notifier.py`, `watch/calibre.py(부분)`, `gui/app_core/sync_control.py` 전부.

CodeGraph로 분석한 호출 관계: `SyncService/run_sync_pipeline` 블라스트 반경(GUI `sync_control`·`x3_websync.py` 호출, 관련 테스트 4종), `SyncHistoryDb needs_sync/mark_synced*` 호출자(파이프라인 2경로 + 백업/로컬임포트 + HistoryTab). CodeGraph 출력의 verbatim 소스는 디스크와 일치함을 2건 표본으로 재확인했다.

실행한 테스트: `python -m pytest -q` 2회(1차 `1 failed, 307 passed`, 종료코드 1 / 2차 `310 passed in 19.58s`, 종료코드 0), `pytest --collect-only -q`(308 collected), `tests/test_multi_pc_history.py` 단독 재실행(통과), `python x3_websync.py --smoke`(OK, v1.2.2).

확인하지 못한 환경/외부 서비스: 실제 X3/X4 기기(전송·파일 API 응답 계약), OneDrive 등 실제 클라우드 클라이언트의 순간 파일 상태, OS별 frozen exe(PyInstaller) 동작, macOS launchd·Linux crontab·Windows schtasks 실등록, YouTube/OpenAI/Ollama/LibreTranslate 외부 API, Calibre 실연동.

분석상 한계 (정직한 기록):

- `AGENTS.md`는 저장소에 존재하지 않아(`Test-Path` False) 확인할 수 없었다. 본 감사에서는 `README.md`·`CLAUDE.md`·설정/빌드 파일을 기준으로 삼았다.
- 작업트리가 감사 도중에 변경되었다(§4 ISSUE-001). 모든 열람 근거·테스트 수치는 관측 시점(point-in-time) 값이며, `device_ids.py`는 열람본과 최종본이 다르다(최종본 기준 재검증: 서명·단독 테스트·전체 스위트).
- CodeGraph 합성 단계(별도 워크플로우)는 근거 부족으로 미완료 처리하고, 본서는 직접 열람 근거만으로 작성했다. Speculative는 High-Risk에 넣지 않았다.
- `dead code`로 판단한 것은 risk로 계상하지 않았다(`register_scraper` 무호출 등).

## 4. High-Risk Issues

### [ISSUE-001] 감사 중 미커밋 alias-id 변경과 미추적 테스트의 충돌로 스위트가 적색→녹색으로 변동

- **위치:** `websync/upload/device_ids.py` (`build_targets_with_keys`, `_clean_alias_ids`), `tests/test_multi_pc_history.py` (미추적), 연관 미커밋 파일 `websync/backup/*`, `websync/config/manager.py`, `websync/upload/uploader.py`, `websync/gui/app_core/helpers.py`, `websync/pipeline/*`
- **우선순위:** High
- **신뢰도:** Confirmed (관측 사실; 원인은 Likely가 아니라 관측으로 확정 — 아래 근거)
- **문제:** 1차 `pytest -q`에서 `test_same_reader_on_another_pc_skips_posts_already_sent`가 `TypeError: build_targets_with_keys() got an unexpected keyword argument 'primary_alias_ids'`로 실패(1 failed, 307 passed, exit 1)했는데, 이후 동일 테스트 단독 실행은 통과하고 전체 재실행은 `310 passed`가 됐다. 테스트 총수 자체도 308 → 310으로 변했다.
- **발생 조건:** `alias_ids`(기기 별칭 ID: PC가 바뀌어도 같은 리더기로 인식) 기능이 7개 소스 파일(`backup/device_registry.py`, `config/manager.py`, `gui/app_core/helpers.py`, `pipeline/preview.py`, `pipeline/service.py`, `upload/device_ids.py`, `upload/uploader.py`)과 미추적 테스트 1개에 걸쳐 미커밋 상태로 부분 착지되어 있고, 감사(또는 병행 작업) 도중 파일이 추가로 변경됨.
- **영향:** 릴리스 게이트(`pytest -q` 종료코드)가 비결정적. 부분 착지된 기기 식별 변경이 섞이면 다중 기기/다중 PC 중복 제거(`needs_sync`·`alias_key_groups`) 동작을 확정할 수 없다.
- **근거:** 1차 실행 tail(`1 failed, 307 passed`), 단독 재실행(`1 passed`), 최종 전체(`310 passed in 19.58s`), `git status`(9 modified + 1 untracked), `git diff`(작업트리에 `primary_alias_ids` 존재), 최종 서명 재확인(`(x3_ip, devices=None, *, primary_id='', primary_alias_ids=None, primary_name=None)`).
- **반증 확인:** 제품 로직 결함이 아님을 확인했다 — 동일 코드·동일 테스트의 재실행은 모두 통과하므로, 원인은 코드가 아니라 감사 창구간의 트리 변경이다. `git stash`/되돌리기는 하지 않았다(감사 범위 외 + 미커밋 사용자 자산 보호).
- **호출/영향 범위:** `build_targets_with_keys` 호출자는 CodeGraph 기준 파이프라인·프리뷰·백업·테스트 전반. `alias_ids` 참조 파일이 식별·이력·GUI·백업에 분산되어 있어 영향면이 넓다.
- **권장 수정 방향:** alias-id 변경 일체를 하나의 커밋(또는 되돌리기)으로 정리하고 미추적 테스트를 추적 편입한 뒤, 클린 트리에서 `pytest -q`를 게이트로 고정한다. 기능 자체(별칭 ID 병합)는 방향이 맞으므로 되돌리기보다 정리를 권장한다.
- **필요한 회귀 테스트:** `test_multi_pc_history.py`를 그대로 게이트에 둔다(통과 중). 추가: 동일 리더기·다른 PC·다른 IP에서 `needs_sync == False` 유지 + `x3_primary_device_id` 불변 + 별칭 누적 상한(무한 증가 방지) 단위 테스트.

### [ISSUE-002] `test_connection`이 HTTP 상태코드를 보지 않아 무관한 서버에도 "연결됨" 반환

- **위치:** `websync/upload/uploader.py:197-206` (`X3Uploader.test_connection`)
- **우선순위:** Medium
- **신뢰도:** Confirmed (코드 확정)
- **문제:** `requests.get(url, timeout=3)` 뒤 상태코드 검사 없이 `return True`. 오타 IP에 라우터 관리페이지·다른 웹서버가 있으면 연결 체크가 성공처럼 보인다.
- **발생 조건:** 입력한 주소에 HTTP 404/500 등을 반환하는 임의 서버가 응답하고, 사용자가 [연결 확인] 성공을 믿고 동기화를 실행.
- **영향:** 연결 체크의 거짓 양성 → 후속 동기화 실패 발견 지연. 기기 손상·데이터 유실은 없다.
- **근거:** 해당 함수 본문 10줄 — `try: requests.get(...); return True / except: return False`. 호출자는 GUI 연결 확인 경로(CodeGraph상 ಗು이 계열).
- **반증 확인:** 상위 caller의 추가 검증을 찾지 못했다(함수 자체가 검증층). `device_client.get_status()`는 200·JSON·dict를 엄격 검사하므로 대체 수단이 존재하지만, uploader 경로에서는 쓰이지 않는다.
- **호출/영향 범위:** GUI 연결 확인 버튼 → `test_connection`. 파이프라인 업로드 판정에는 영향 없음(실전송 결과로 판단).
- **권장 수정 방향:** 2xx 요구(최소 `response.ok`), 가능하면 `GET /api/status` + JSON 확인으로 격상. 타임아웃 3초는 유지.
- **필요한 회귀 테스트:** stub 서버에 200/404/500·타임아웃을 차례로 주고 `True/False/False/False`를 assert하는 단위 테스트.

### [ISSUE-003] 선택 동기화·프리뷰가 취소 이벤트를 확인하지 않아 종료 계약이 깨짐

- **위치:** `websync/pipeline/selected_sync.py` (전문 — `is_cancel_requested` 호출 없음), `websync/pipeline/preview.py` (동일)
- **우선순위:** Medium
- **신뢰도:** Likely (코드 근거 강함, 런타임 재현은 못함)
- **문제:** 전체 파이프라인(`sync_pipeline.py:115`)은 사이트 경계마다 취소를 검사하지만, 선택 동기화·프리뷰에는 검사가 없다. `_on_close`(`gui/app_core/sync_control.py:122-143`)는 `request_cancel → shutdown_pipeline(5s) → flush_backup_push → _wait_for_background_tasks(5s) → destroy`인데, 대상 스레드가 취소를 모르므로 대기만 소진하고 종료로 진행한다.
- **발생 조건:** 대량 선택 동기화(또는 느린 사이트 프리뷰) 실행 중 앱 종료.
- **영향:** 종료 지연(최대 ~10초 대기 후 진행), 데몬 워커가 업로드/DB 쓰기 도중 인터프리터 종료와 yarış. 무결성 파탄은 관찰되지 않았다(기록은 전송 성공 후에만, 트랜잭션은 짧음).
- **근거:** 두 파일 전문에 `cancel` 언급 전무 vs 전체 파이프라인의 명시적 검사. `shutdown_pipeline`은 등록된 `_pipeline_thread`만 join하며 선택/프리뷰 워커는 추적 집합에만 있다.
- **반증 확인:** DB 락·트랜잭션·성공 후 기록 구조상 데이터 손상으로 비화할 경로는 찾지 못해 심각도를 Medium으로 제한했다. 서버/`watcher` 중지·백업 flush 순서는 올바르다.
- **호출/영향 범위:** GUI 선택 전송·미리보기 버튼 → 해당 함수 → uploader/DB. 대시보드 `/api/sync`는 비차단 기동이라 영향 없음.
- **권장 수정 방향:** 선택 동기화에 기사/사이트 경계 취소 검사 추가(전체 파이프라인과 동일 메시지 계약), 프리뷰에 사이트 경계 검사 추가. 또는 `shutdown_pipeline`이 추적 워커까지 join하도록 확장.
- **필요한 회귀 테스트:** ① 50개 선택 기사 + 즉시 `request_cancel` → `success == False`이며 `mark_synced` 호출 0건. ② 종료 시퀀스 모의 — `shutdown_pipeline`이 5초 안에 `is_pipeline_running == False`를 반환.

### [ISSUE-004] Linux crontab 등록/해제가 사용자가 직접 추가한 크론 줄을 함께 삭제

- **위치:** `websync/scheduler/manager.py:181` (`_register_linux`), `:214` (`unregister_task`)
- **우선순위:** Low
- **신뢰도:** Confirmed (코드 확정)
- **문제:** 기존 크론탭 정리 조건이 `TASK_NAME not in l and script_path not in l` — 앱과 무관하게 `script_path` 문자열이 들어간 사용자 커스텀 줄(예: 수동으로 추가한 시간별 실행)도 삭제된다. 백업 없이 `crontab -`로 덮어쓴다.
- **발생 조건:** Linux에서 동일 스크립트 경로를 언급하는 별도 크론 줄이 있고, GUI에서 스케줄 등록/해제를 수행.
- **영향:** 사용자 크론 설정 유실(복구 가능, 조건 협소). Windows/macOS 경로에는 해당 없음.
- **근거:** 해당 2줄의 필터 조건. macOS plist는 전용 파일이라 무영향, Windows는 `schtasks /tn` 단건 삭제라 무영향.
- **반증 확인:** `shell=False` argv 실행·`shlex.quote` 처리는 확인되어 인젝션 문제는 아니다. 삭제 범위가 문제의 전부다.
- **호출/영향 범위:** GUI 스케줄 UI → `register/unregister_task` → 사용자 크론탭 전체.
- **권장 수정 방향:** `# XteinkX3WebSyncTask` 마커 블록(시작/종료 주석) 사이의 줄만 관리하고 나머지 줄은 그대로 둔다. 쓰기 전 기존 크론탭을 `logs/cron.bak`에 백업.
- **필요한 회귀 테스트:** 커스텀 줄(`*/30 * * * * /.../x3_websync.py --sync --custom`)이 포함된 가짜 크론탭 입력에 등록/해제를 dry-run → 커스텀 줄 보존 assert.

### [ISSUE-005] 사이트 `limit` 검증이 권고에 그쳐 비정상값이 스크래퍼까지 도달

- **위치:** `websync/config/validator.py:111-117` (1~100·정수 검사), `websync/config/manager.py` (`log_validation_warnings` 호출만), `websync/scrapers/css.py:53-69`·`rss.py:48-65` (`[:limit]` 직접 슬라이싱)
- **우선순위:** Low
- **신뢰도:** Confirmed (코드 확정)
- **문제:** 검증 실패가 경고 로그로만 끝나고 로드·저장·파이프라인을 막지 않는다. 수동 편집·임포트로 들어온 비정상 `limit`가 그대로 슬라이싱에 쓰인다. 문자열이면 사이트 에러(복구 가능), 음수이면 `[:-1]`처럼 조용히 수집 개수가 달라진다(에러 없이).
- **발생 조건:** `limit`이 범위를 벗어나거나 문자열인 설정을 파일로 직접 작성/임포트.
- **영향:** 특정 사이트의 수집 누락 또는 과소 수집. 다음 실행에 재시도 가능하며 DB·기기 영향 없음.
- **근거:** validator 본문 + `load_config`의 `log_validation_warnings` 호출(차단 없음) + 양 스크래퍼의 무검증 슬라이싱.
- **반증 확인:** GUI 입력 경로의 별도 clamp는 확인하지 못했으나, 문제 경로는 파일 직접 편집이므로 GUI clamp가 있어도 막지 못한다. 스키마 버전 보강(`_merge_sites`)도 값 범위는 정규화하지 않는다.
- **호출/영향 범위:** 설정 파일·임포트 → 전체/선택/프리뷰 파이프라인의 모든 스크래퍼 호출.
- **권장 수정 방향:** 스크래퍼 진입점에서 `limit`를 `int` 변환 + `1..100` clamp 후 사용(실패 시 기본 5). validator는 현행 유지.
- **필요한 회귀 테스트:** `limit`에 `-1/0/101/"abc"/None`을 준 CSS·RSS 단위 테스트 → 수집 건수가 clamp 규칙과 일치 assert.

## 5. Potential Functional Gaps

- **Confirmed Gap — `AGENTS.md` 부재.** 감사 지시문은 `AGENTS.md` 확인을 요구했지만 저장소에 파일이 없다. 에이전트 협업 규칙이 `CLAUDE.md`에만 있어 진입 장벽이 된다. (추정 아님 — `Test-Path`로 확인)
- **Likely Gap — 업로드 재시도 없음.** `upload_to_targets`는 IP당 1회 POST이며, 일시적 Wi-Fi 끊김은 해당 사이트 실패로 끝나 다음 예약 실행까지 연기된다. 종료코드 1(`--sync`)과 토스트는 나가므로 감지는 되지만,同一 실행 내 1회 재시도(멱등: 동일 파일·동일 파일명)만으로 복구가 가능한 실패까지 미룬다.
- **Likely Gap — 손상 설정 복구가 수동.** 손상 JSON은 `.corrupt` + `.bak` 보존 후 `ConfigLoadError`로 종료한다(안전한 방향). 다만 GUI/CLI 모두 exit 1 외 복구 유도(백업에서 복원 프롬프트)가 없어 일반 사용자가 멈춘다.
- **추정 — frozen(exe) 배포물 미검증.** 본 감사는 소스 실행(Linux 아님, Windows) 기준이며, `paths.py` frozen 분기·`x3_websync.spec` hiddenimports·단일 인스턴스 mutex의 실배포 동작은 확인하지 못했다.
- **추정 — OS별 스케줄러 실등록 미검증.** 인용·이스케이프는 코드로 확인(Windows 인용, macOS XML escape, Linux shlex)했으나 세 OS 실등록 테스트는 수행하지 못했다.
- **추정 — 실제 펌웨어 응답 계약 미검증.** `device_client`의 상태·목록·삭제·개명·이동·다운로드 분기와 타임아웃(8/15/30/120s)은 코드상 타당하나, 실기기 multipart 중단·비표준 응답은 이전 감사와 동일하게 운영 검증 항목으로 남는다.
- **추정 — 셀렉터 도우미와 공유 세션의 동시 사용 미검증.** 파이프라인·프리뷰·선택 경로는 락으로 직렬화되나, 셀렉터 마법사 경로가 병행 실행될 때 모듈 공유 `_session`의 스레드 안전성은 확인하지 못했다.

> 이전 감사(2026-09-20) remediation 보존 기록: ① 공유 JSON strict reader(`atomic_io.read_json_checked` + 재시도 후 중단) ② tombstone/이력 시각 절대비교(`import_deleted_posts`의 `_time_key`, 재전송이 오래된 tombstone에 지워지지 않음) ③ 기기별 missing 집합별 배치(`group_articles_by_pending_targets` + `collect_mark_entries`) ④ OPDS XML escape + UTC mtime — 모두 본 감사에서 코드 존재를 재확인했다.

## 6. Documentation Mismatches

- **`AGENTS.md` 없음.** 지시문 전제와 달리 파일이 존재하지 않는다(있으면 있다고, 없으면 없다고 명시 요구에 따라 기록).
- **CLAUDE.md 표본 대조 — 불일치 없음(표본 한정).** 스크래퍼 13종·DB `timeout=10.0`·업로드 타임아웃식(25s + 5s/MB)·락 설계·원자 저장·스크래퍼 가이드가 실코드와 일치함을 표본 확인했다. 전체 문서 diff는 수행하지 않았다.
- **README.md 진입점 — 표본상 일치.** `--sync`/`--smoke`/`--check-update`/`--version` + 히든 업데이트 인자가 실 `argparse`와 일치한다. 히든 인자가 README에 없는 것은 의도적(SUPPRESS)으로 보인다.
- **수치 변경(불일치가 아니라 경과 기록).** 이전 문서의 "307 passed@v1.2.1"に対し 본 감사 최종은 "310 passed@v1.2.2"(미커밋 변경 포함). 이전 문서가 거짓이 아니라 버전·트리 차이임을 명시한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate (게이트 복원, 코드 0~소규모)

1. ISSUE-001: alias-id 변경 커밋(또는 revert) + `tests/test_multi_pc_history.py` 추적 편입 → 클린 트리에서 `pytest -q` 녹색 고정. CI에 `git status --porcelain` 비어 있음 조건 또는 변경분 커밋 강제.
2. ISSUE-002: `test_connection`에 2xx 요구(또는 `/api/status` 확인). 10줄 이내 수정.
3. ISSUE-004: crontab 마커 블록 관리 + 쓰기 전 백업.

### Phase 2 — Stability (예외·검증·상태)

4. ISSUE-003: 선택/프리뷰 경로에 취소 검사 추가(전체 파이프라인과 동일 계약).
5. ISSUE-005: 스크래퍼 진입점 `limit` clamp(1~100, 기본 5).
6. Likely Gap: 업로드 1회 재시도(동일 파일 멱등) + 손상 설정 시 `.bak` 복원 안내 메시지.

### Phase 3 — Structural (구조·검증 가능성)

7. 설정 검증을 경고/차단 2단계로 분리(차단은 스키마 파괴 수준만).
8. 실기기·실클라우드·3 OS 스케줄러·frozen exe의 운영 검증 체크리스트를 `docs/DEVELOPER.md`에 고정.
9. 셀렉터 마법사 경로의 세션 사용을 팩토리 주입으로 바꿔 동시성 테스트 가능하게 분리.

실제 코드는 수정하지 않는다(본 감사는 리포트のみ).

## 8. Test Recommendations

- **T1 게이트 결정성 (ISSUE-001 회귀).** 입력: 클린 체크아웃에서 `pytest -q`. 기대: exit 0 + `310 passed`(테스트 수 변경 시 카운트 갱신). `git status --porcelain` 비어 있음과 함께 CI에서 실행.
- **T2 연결 판정 (ISSUE-002 회귀, Unit).** 입력: stub HTTP 200 with JSON / 404 / 500 / 타임아웃에 `test_connection`. 기대: `True/False/False/False`.
- **T3 선택 동기화 취소 (ISSUE-003 회귀, Integration).** 입력: 선택 기사 50건 + 즉시 `request_cancel`. 기대: `False` 반환, `mark_synced_many` 0회, `is_pipeline_running == False`.
- **T4 프리뷰 취소·락 (ISSUE-003/동시성).** 입력: 느린 사이트 프리뷰 중 `run_sync_pipeline` 호출. 기대: 둘 중 하나는 `False`/빈 결과로 즉시 복귀, 데드락 없음.
- **T5 crontab 보존 (ISSUE-004 회귀, Unit/dry-run).** 입력: 커스텀 줄 포함 가짜 크론탭에 등록·해제. 기대: 커스텀 줄 보존, 마커 블록만 변경.
- **T6 limit clamp (ISSUE-005 회귀, Unit).** 입력: `limit` = -1/0/101/"abc"/None인 사이트 설정. 기대: 1~100 clamp(실패 시 5) 수집.
- **T7 부분 실패 기록 정확성 (E2E 모의).** 입력: 2기기 중 1대만 업로드 성공하도록 stub. 기대: 성공 기기만 `is_synced_for_device == True`, 실패 기기는 다음 실행에 `needs_sync == True`.
- **T8 다이제스트 모드 (Integration).** 입력: `epub_merge_mode=daily_digest` + 기기별 missing 집합 상이. 기대: 집합별 별도 EPUB·전송·기록(이전 remediation 유지).
- **T9 종료 순서 (Concurrency).** 입력: 동기화 실행 중 `_on_close` 모의. 기대: 서버 중지 → 파이프라인 종료(≤5s) → 백업 flush → 워커 대기(≤5s) → destroy 호출.
- **T10 손상 공유 JSON (Regression).** 입력: 0바이트·깨진 `sites.json`/`synced_posts.json`에 pull/push. 기대: 중단 + 원본 미변경(이전 remediation 유지).
- **T11 tombstone 우선순위 (Regression).** 입력: 삭제 → 재전송 → 오래된 tombstone 재수신. 기대: 최신 이력 유지(이전 remediation 유지).
- **T12 플랫폼별 (Platform-specific).** 입력: 공백·`&`·유니코드 포함 경로의 스케줄러 명령 생성(dry-run). 기대: Windows 인용·plist escape·crontab quote 정상(실등록 없이 문자열 assert).

## 9. Final Assessment

| 영역 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 핵심 흐름 정확. 단 연결 판정 거짓 양성(002)·limit clamp 누락(005)이 남음 |
| Runtime Stability | Acceptable | 락·종료 순서 견고. 단 선택/프리뷰 취소 공백(003)이 종료 계약을 깬다 |
| Data Integrity | Good | 성공분만 기록·원자 저장·tombstone·트랜잭션 확인. 로컬 파이프라인 유실 경로 없음 |
| Error Resilience | Acceptable | 사이트별 격리·재시도 세션. 단 업로드 재시도 없음·손상 설정 수동 복구 |
| Cross-platform Robustness | Acceptable | 인용·이스케이프 코드 확인. 단 실OS 등록·frozen 미검증, crontab 과삭제(004) |
| Test Confidence | Acceptable | 최종 310 passed·스모크 OK. 단 감사 중 트리 변경으로 게이트 결정성 결함(001), 실기기·실클라우드 공백 |

**실제로 먼저 수정할 문제 3개:**

1. **작업트리 정리 + 클린 게이트 (ISSUE-001)** — alias-id 변경 커밋과 미추적 테스트 편입, 클린 트리 `pytest -q` 고정. 다른 모든 수정 전제 조건.
2. **`test_connection` 상태코드 검사 (ISSUE-002)** — 10줄 수정으로 거짓 양성 제거, 사용자-facing 효과 최대.
3. **선택/프리뷰 취소 처리 (ISSUE-003)** — 종료 계약 복원. crontab 범위 축소(ISSUE-004)·limit clamp(ISSUE-005)는 같은 Phase에 묶어 처리.

## Addendum — Remediation applied (2026-09-22, v1.2.3)

위 스냅샷 이후 ISSUE-002~005를 수정하고 `pytest -q` 324 passed, `--smoke` OK를 확인했다.

- ISSUE-002: `X3Uploader.test_connection`·`X3DeviceClient` 폴백이 2xx를 요구. 테스트 `test_test_connection_requires_2xx_status` 등 추가.
- ISSUE-003: `selected_sync` 사이트·배치 경계와 `preview` 사이트 경계에 취소 검사 추가. 회귀 테스트 `test_selected_sync_returns_false_when_cancelled`, `tests/test_preview.py` 추가.
- ISSUE-004: crontab은 `BEGIN/END` 마커 블록만 관리하고 사용자 줄을 보존. 쓰기 전 `logs/cron.bak` 백업. 회귀 테스트 4건 추가.
- ISSUE-005: `base.normalize_limit`(1~100, 실패 시 기본값)을 11개 스크래퍼 진입점에 적용. `tests/test_scraper_limits.py` 추가.
- ISSUE-001(작업트리 정리)은 alias-id 기능 커밋(`device_registry`, `devices` 페이로드, 문서 갱신)과 함께 v1.2.3에 포함했다.
