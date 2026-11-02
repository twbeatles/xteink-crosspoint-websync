# Project Audit

> 후속 개선: 이 감사의 ISSUE-001~003과 §5·§6·§7 권고(원격 receipt 모델 제외)를 구현했다. 아래 이슈·평가는 감사 당시 기록이며 현재 미수정 목록이 아니다. [구현 대조표와 검증 근거](docs/AUDIT_IMPLEMENTATION.md#2026-11-02-후속-구현)를 참조한다.

> 감사일: 2026-11-02 (Asia/Seoul) · 기준: `main`, `7560567` (v1.4.0)
>
> 기능 구현·런타임 안정성 감사. 애플리케이션·테스트 코드는 바꾸지 않았고 이 보고서만 다시 작성했다. 이전 감사(2026-10-21, `5caebe4`)의 ISSUE-001~004와 후속 권고는 `ee3027b`·`f7d6e8c` 등에서 구현되었음을 코드로 다시 확인했다(아래 §3). 이전 보고서 본문은 git 이력과 [docs/AUDIT_IMPLEMENTATION.md](docs/AUDIT_IMPLEMENTATION.md)에 남아 있다. 아래 이슈 번호는 이번 감사에만 해당한다.

## 1. Executive Summary

**전체 상태: Good(일부 Acceptable). 전체 위험도: Low.**

핵심 경로(수집 → 기기별 중복 판정 → EPUB → 업로드 → 성공 기기만 이력 기록 → 공유 폴더 push)는 일관되게 구현되어 있다. 지난 감사 이후 변경(EPUB 파일명 `hash8`, 업데이트 종료 drain 통합, 선택 전송 push, 설정 복구 완화, 충돌 병합 필드별 처리, 업데이터 이동식 교체, EPUB 정화 확장, 프리셋 카테고리)을 추적했다. 새로 생긴 회귀는 찾지 못했다. 전체 테스트는 **703 passed, 28 skipped**(27건은 네트워크가 필요한 라이브 계약, 1건은 POSIX 전용)다.

반증 확인 뒤 남은 문제는 다음 3개다. Critical·High는 없다.

| 이슈 | 심각도 / 신뢰도 | 요약 |
|---|---|---|
| ISSUE-001: 기기 파일 다운로드가 같은 이름의 로컬 파일을 경고 없이 덮어씀 | Medium / Confirmed | 반대 방향(수동 업로드)에는 덮어쓰기 경고가 있지만 다운로드는 성공 시 `os.replace`로 기존 PC 파일을 교체한다. 되돌릴 수 없다 |
| ISSUE-002: Windows 스케줄 등록 실패 시 `schtasks` 오류 사유가 사용자에게 전달되지 않음 | Low / Confirmed | 261자 초과만 구체적 사유가 나오고, 권한·정책·이름 문제 등 schtasks 자체 실패는 일반 문구만 표시된다 |
| ISSUE-003: OPDS 카탈로그의 요약 제목 정리 정규식이 한 번도 일치하지 않음 | Low / Confirmed | `_`를 공백으로 바꾼 뒤 `_날짜.epub`를 찾기 때문에 항상 실패한다. v1.4.0의 `_hash8` 접미사로 더 어긋난다. 표시만의 문제다 |

**데이터 손상·유실 가능성:** SQLite 이력, `config.json`, 공유 폴더 JSON이 손상될 경로는 찾지 못했다. 저장은 원자적 교체(tmp + fsync + `os.replace`), 구조 검증, 프로세스 락, revision CAS로 보호된다. 유일한 유실 경로는 ISSUE-001이다. 사용자가 직접 고른 폴더에서, 같은 이름의 **로컬 파일 1개가 교체되는** 범위로 한정된다.

**가장 먼저 수정할 영역:** 기기 파일 다운로드의 로컬 충돌 처리(ISSUE-001). 다음은 스케줄 등록 실패 사유 노출(ISSUE-002)이다.

## 2. Project Understanding

### 목적

CrossPoint 펌웨어를 쓰는 Xteink X3/X4 e-ink 리더기용 데스크톱 동반 앱이다. 웹·RSS·블로그·뉴스레터·YouTube 자막을 수집해 EPUB으로 만들고, 기기의 HTTP `/upload`로 무선 전송한다. 이미 보낸 글은 기기별 SQLite 이력으로 제외한다. 여러 PC는 공유 폴더(`sites.json`, `synced_posts.json`, `.websync-replicas/`)로 구독과 이력을 공유한다. Calibre 서재 전송과 폴더 Watch, 기기 파일 관리, OPDS, 웹 대시보드, Ed25519 서명 자동 업데이트도 제공한다. README, README.ko, CLAUDE.md, AGENTS.md, CONTRIBUTING(main 기본, Spec Kit opt-in), `requirements*.txt`, `.github/workflows/test.yml`, `x3_websync.spec`을 확인했다.

### 주요 entrypoint

| Entry point | 분기 |
|---|---|
| `x3_websync.py:72 main` | `--smoke`, `--apply-update`(헬퍼), `--check-update`, `--recover-config`, `--sync`(CLI, GUI 락 없음), 기본 GUI(단일 인스턴스 락) |
| `gui/app_core/sync_control.py` | 즉시 동기화, 백그라운드 작업 추적, `_on_close(after_drain=)` 종료 drain |
| `gui/sync_tab/preview.py` | 미리보기 → 선택 전송 / EPUB만 만들기 |
| `servers/dashboard/handler.py` | `/api/login`, `/api/sync`(202/409), `/api/cancel`, `/api/status`, `/api/log` |
| `servers/opds.py` | `/opds` 카탈로그, `/opds/download/<file>` |
| `gui/settings_tab/watch.py` + `watch/` | Calibre 폴더 감시 → 영속 재시도 큐 |
| `scheduler/manager.py` | schtasks / launchd / crontab → `--sync` |
| `gui/settings_tab/updater.py` | 확인 → 다운로드·검증 → drain 후 헬퍼 기동 |

### 핵심 모듈과 저장 방식

- `pipeline/service.py`(SyncService): 스레드 락 + 프로세스 파일 락, 작업 수락·취소, 백업 pull/push 훅, `_last_pipeline_result`.
- `pipeline/sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py`, `sources.py`: 전체·선택·미리보기·파일 전용 흐름, URL 기반 `source_id`.
- `config/manager.py`, `validator.py`: `config.json` RMW(`update_config`, `patch_fields`), revision CAS(`save_config(expected_revision=)`), 저장 전 구조 검증, `.bak`·`.corrupt`·`.rejected.*` 보존.
- `db/history.py`: `synced_posts(url, device_ip)` 복합 PK, `deleted_posts` tombstone, 작업별 연결 + commit/rollback, WAL, `timeout=10`.
- `upload/uploader.py`, `device_client.py`, `device_ids.py`: 전송명(원래 문자 + 원본 basename MD5 6자리), 안정 기기 ID·alias 키, 기기 파일 REST.
- `epub/builder.py`, `sanitize.py`: `{사이트}_{날짜}_{hash8}.epub`, 위험·XHTML 비호환 태그 제거.
- `backup/`: 공유 폴더 병합. 스레드 락과 폴더 파일 락으로 pull/push를 직렬화한다.
- `core/update/`: 서명 manifest, 스트리밍 크기·SHA256 검증, 이동식 교체·smoke·롤백.
- 외부 의존성: requests, beautifulsoup4/lxml, ebooklib, customtkinter, cryptography(필수). Pillow, googletrans, youtube-transcript-api, watchdog, Calibre CLI는 선택.

### 핵심 실행 흐름

1. **전체 동기화:** `GUI/CLI/Dashboard → SyncService._try_acquire_pipeline_locks → maybe_backup_pull → run_sync_pipeline_locked → ScraperFactory.get_scraper().fetch_articles → db.needs_sync(alias 키) → (번역/요약) → group_articles_by_pending_targets → EpubBuilder.build/build_digest → X3Uploader.upload_to_targets → collect_mark_entries → db.mark_synced_many → maybe_backup_push → _release_pipeline_locks`
2. **미리보기·선택 전송:** `preview_articles(락·pull·수집·중복 판정, 기록 없음) → GUI 선택 → sync_selected_articles(락 → pull → selected_source_groups → 기기별 배치 build/upload/mark → 정상 완료 또는 기록 1건 이상이면 push → 락 해제)`
3. **EPUB만 만들기:** `build_selected_epubs → 공통 락 → build/build_digest → 경로 반환`(전송·이력 없음)
4. **Watch:** `watchdog 이벤트 → 디바운스·안정 크기 → WatchRetryQueue.enqueue(config.pending_jobs 저장) → 파이프라인 락 → upload_to_targets(미완료 대상만) → 완료 저장/제거 또는 지수 backoff`
5. **기기 파일:** `DeviceFilesTab → X3DeviceClient.list_files/download/upload_to_path/delete_paths/rename/move → CrossPoint /api/files 등`
6. **종료·업데이트:** `_on_close → prepare_shutdown → 서버·Watch 정지 → shutdown_pipeline 대기 → 백그라운드 작업 대기 → flush_backup_push → (after_drain: launch_update_helper) → root.destroy` → 헬퍼: 부모 종료 대기(15초) → 타겟을 백업으로 이동 → staged를 타겟으로 이동 → `--smoke` → 실패 시 롤백 → 결과 파일 → 재기동

## 3. Audit Coverage & Limitations

### 확인한 모듈

- **CodeGraph MCP(`codegraph_explore`)로 소스와 호출 관계를 확인했다:** `apply_staged_update`·`launch_update_helper`·`UpdateService.launch_update/launch_update_and_exit`(호출자 `settings_tab/updater.py`, 테스트 `test_update_swap_regression.py`); `_on_close`·`is_pipeline_running`(호출자 14곳); `DashboardHandler.do_GET/do_POST`·`session_valid`·`OPDSHandler._check_auth/_serve_file`; `group_articles_by_pending_targets`·`needs_sync`·`is_synced_for_any_key`·`alias_key_groups`·`collect_mark_entries`·`mark_synced_many`(호출자 `sync_pipeline.py`, `selected_sync.py`); `_safe_save_config`·`_save_ui_settings`·`save_config`(호출자 35곳)·`ConfigConflictError`.
- **직접 열람(bash/grep)으로 보완했다:** 지난 감사 이후 diff 전체(`git diff 5caebe4..HEAD -- websync x3_websync.py`, 19개 파일), `sync_pipeline.py` 전체, `selected_sync.py` 전체, `service.py`(락·push·종료), `config/manager.py`(load/save/RMW/`_normalize_loaded`), `uploader.py`, `device_client.py`(list/download), `gui/device_files/actions.py`·`cleanup.py`, `upload/sync_epub.py`·`remote_path.py`, `tab_history.py`, `scheduler/manager.py`, `summarizer.py`·`translator.py`(timeout), `scrapers/base.fetch_url`, `x3_websync.py main`, `cli/update_apply.py`, `backup/service.py` 락 구조.
- 지난 감사 권고의 구현 확인: 빌더 파일명 `_batch_digest`(`builder.py:20`), `launch_update` + `_on_close(after_drain=)`(`updater.py`, `sync_control.py:233`), 실행 중 작업이면 적용 거부, 선택 전송 push(`selected_sync.py:47-71`), `restore_config` 의미 경고 허용, 충돌 병합의 백그라운드 필드 보존(`helpers.py:_merge_config_on_conflict`), schtasks 길이 사전 거부, `romanize.py` 삭제.

### 실행한 검증

환경: **Windows 11 / Python 3.15.1**.

```text
python -m pytest -q -x -p no:cacheprovider
703 passed, 28 skipped, 13 warnings in 104.23s
skip: tests/test_preset_epub_pipeline.py:185 (27건) — WEBSYNC_LIVE_CONTRACTS=1 필요
      tests/test_storage_isolation.py:121 (1건) — POSIX directory descriptors
warnings: 외부 패키지 langsmith의 asyncio DeprecationWarning (프로젝트 코드 아님)
```

저장소에 파일을 추가하지 않고 세션 임시 폴더에서 일회성 재현을 실행했다. import 전에 `X3_WEBSYNC_STORAGE_ROOT`를 임시 폴더로 지정했고, 출력에서 `PROJECT_ROOT`가 임시 경로임을 확인했다.

| 재현 | 결과 |
|---|---|
| R1: `EpubBuilder.build("테크뉴스", …)` 결과 파일명에 OPDS `_serve_catalog`의 제목 정리식 적용 | 파일 `테크뉴스_2026-11-02_c070adea.epub` → 제목 `'테크뉴스 2026-11-02 c070adea.epub'`(날짜·확장자가 제거되지 않음) |
| R2: 로컬에 `book.epub`(내용 `USER-OWN-LOCAL-BYTES`)가 있는 폴더로 `X3DeviceClient.download("/book.epub", …)` (requests.get은 fake 200 응답) | 오류·확인 없이 로컬 파일이 `DEVICE-BYTES`로 바뀜 |

`git status`로 작업 트리가 감사 전과 같음을 확인했다(기존 미추적 `AGENTS.md`만 있음).

### 한계

- 실제 X3/X4와 CrossPoint 펌웨어가 없다. 같은 경로 업로드 의미, 한글 multipart 파일명 표시, 기기가 보고하는 파일명 형식은 확인하지 못했다(`docs/AUDIT_VALIDATION.md` 범위).
- frozen EXE로 실제 업데이트 헬퍼를 실행하지 않았다. 교체 로직은 코드와 기존 테스트(`test_update_swap_regression.py`)에 근거해 판단했다.
- 외부 사이트(라이브 프리셋 27건), AI/번역 provider, Calibre, 클라우드 동기화 클라이언트, macOS/Linux의 실제 스케줄러·GUI는 확인하지 않았다.
- CodeGraph는 AST 기반 정적 분석이다. Tk 콜백, 스레드 target, `after_drain` 람다 같은 동적 연결은 소스를 직접 읽어 판단했다. GUI 위젯 상호작용은 실행하지 않았다.
- 사용자 `config.json`·`sync_history.db`·`output/`은 열거나 수정하지 않았다. 의존성도 설치하지 않았다.

## 4. High-Risk Issues

### [ISSUE-001] 기기 파일 다운로드가 같은 이름의 로컬 파일을 경고 없이 덮어씀

- **위치:** `websync/gui/device_files/actions.py:226 _download_selected`(L249–251), `websync/upload/device_client.py:261 X3DeviceClient.download`(L305 `os.replace(temp_path, local_path)`).
- **우선순위:** Medium
- **신뢰도:** Confirmed (코드 흐름 + R2)
- **문제:** 다운로드 대상 경로는 `os.path.join(dest_dir, item["name"])`이고, 존재 여부를 확인하지 않는다. 임시 `.part` 파일에 받은 뒤 `os.replace`로 교체하므로 기존 파일은 항상 대체된다. 반대 방향인 수동 업로드는 `warn_overwrite`(기본 켜짐)로 `remote_file_exists`를 확인하고 경고한다(`actions.py:301`). 이 설정의 문구는 "수동 업로드 시"로 한정되어 있어 다운로드에는 아무 보호가 없다.
- **발생 조건:** 사용자가 기기 파일 탭에서 파일을 선택해 PC 폴더(예: 다운로드, Calibre 가져오기 폴더, 이전 백업 폴더)로 받는다. 그 폴더에 같은 이름의 파일이 이미 있다. 같은 책의 다른 판본이나, 이전에 받아 PC에서 수정한 파일이 흔한 예다. 여러 파일을 한 번에 받으면 확인 대화상자 없이 모두 처리된다.
- **영향:** 기존 로컬 파일 내용이 영구 교체된다. 휴지통이나 백업으로 보내지 않는다. 결과 대화상자는 성공 개수만 보여 주어 덮어쓴 사실을 알 수 없다.
- **근거:** R2 출력. `test_device_client.py:193`·`test_crosspoint_http_contract.py:163`은 **실패한** 다운로드가 기존 파일을 보존하는지만 검증한다. 성공한 다운로드가 기존 파일을 바꾸는 경우는 테스트하지 않는다.
- **반증 확인:** (1) `filedialog.askdirectory`는 폴더만 고르며 파일 충돌을 묻지 않는다. (2) `_download_selected`와 `task()`에 존재 확인이 없다. (3) `.part` + `os.replace`는 중간 실패 시 원본을 지키는 장치일 뿐 충돌을 막지 않는다. (4) `warn_overwrite`는 업로드 경로에서만 읽는다(grep으로 사용처 1곳 확인). 실제 GUI에서 도달 가능한 production 경로다.
- **호출/영향 범위:** `DeviceFilesTab(버튼) → DeviceFilesActionsMixin._download_selected → app._start_background_task(task) → X3DeviceClient.download`. `download`의 production 호출자는 이 한 곳이다.
- **권장 수정 방향:** 다운로드 전에 대상 경로들의 존재를 메인 스레드에서 확인한다. 충돌이 있으면 "덮어쓰기 / 건너뛰기 / 이름 바꿔 저장(`name (1).epub`)"을 묻는다. 기본값은 이름 바꾸기로 둔다. 기존 `warn_overwrite` 설정을 다운로드에도 적용하고 문구를 "업로드·다운로드"로 바꾸는 방법도 있다. 결과 대화상자에 덮어쓴 개수를 표시한다.
- **필요한 회귀 테스트:** 기존 로컬 파일 bytes가 `A`인 폴더로 같은 이름을 다운로드(fake 200, bytes `B`)하면 기본 정책에서 원본 `A`가 유지되고 새 파일은 다른 이름으로 저장되어야 한다. 사용자가 "덮어쓰기"를 고르면 `B`가 되어야 한다. 충돌이 없으면 대화상자 없이 저장되어야 한다.

### [ISSUE-002] Windows 스케줄 등록 실패 사유가 사용자에게 전달되지 않음

- **위치:** `websync/scheduler/manager.py:84 _register_windows`(L102–104), 표시 `websync/gui/sync_tab/schedule.py`(`last_error` 사용).
- **우선순위:** Low
- **신뢰도:** Confirmed (코드 흐름)
- **문제:** 2026-10-21 후속 구현에서 `last_error`를 추가했지만 채우는 곳은 `/TR` 길이 초과뿐이다. `schtasks`가 0이 아닌 코드로 끝나면 stdout/stderr를 읽지 않고 `False`만 반환한다. 예외 경로도 `print`만 한다. 그래서 GUI는 일반 문구 "등록 실패"만 보여 준다. 또 출력 디코딩을 `encoding="cp949"`로 고정해, 한국어 외 Windows에서 메시지를 노출하더라도 깨질 수 있다.
- **발생 조건:** 그룹 정책으로 작업 스케줄러가 제한된 PC, 작업 이름 충돌·권한 문제(다른 계정이 만든 같은 이름의 작업), 경로 문제 등으로 `schtasks /create`가 실패한다.
- **영향:** 스케줄 등록이 실패했다는 사실은 알 수 있다. 하지만 원인을 알 수 없어 사용자가 대응하기 어렵다. pythonw/EXE 실행이라 콘솔 `print`도 보이지 않는다. 기능이 조용히 오동작하지는 않는다.
- **근거:** `manager.py:102-104`는 `result.returncode == 0`만 반환한다. `last_error` 대입은 L88(길이 초과)뿐이다. `schedule.py`는 `last_error`가 비어 있으면 일반 문구만 쓴다.
- **반증 확인:** `_refresh_schedule_status`(`manager.py:294`)는 등록 여부만 보고 실패 원인은 보존하지 않는다. 로그 파일에도 기록하지 않는다(`print`는 GUI 모드에서 NullWriter로 버려진다).
- **호출/영향 범위:** `SyncScheduleMixin._register_schedule → SchedulerManager.register_daily_task → _register_windows`. macOS(`launchctl load`)와 Linux(`crontab -`)도 같은 패턴으로 stderr를 버린다.
- **권장 수정 방향:** 실패 시 `last_error = (stderr or stdout).strip()`(길이 제한)을 넣고 logger에도 남긴다. 디코딩은 `locale.getpreferredencoding(False)` 또는 `errors="replace"`를 쓴 OEM 코드 페이지로 한다. macOS/Linux 경로에도 같은 처리를 적용한다.
- **필요한 회귀 테스트:** `subprocess.run`을 `returncode=1, stderr="ERROR: Access is denied."`로 바꾸면 `register_daily_task`가 False를 반환하고 `last_error`에 그 문구가 들어가야 한다. 예외 발생 시에도 `last_error`가 비어 있지 않아야 한다.

### [ISSUE-003] OPDS 카탈로그 요약 제목 정리 정규식이 일치하지 않음

- **위치:** `websync/servers/opds.py:103 _serve_catalog`(L117).
- **우선순위:** Low
- **신뢰도:** Confirmed (R1)
- **문제:** `re.sub(r"_\d{4}-\d{2}-\d{2}\.epub$", "", fname.replace("_", " "))`는 밑줄을 먼저 공백으로 바꾼 뒤 밑줄로 시작하는 패턴을 찾는다. 그래서 어떤 파일명에도 일치하지 않는다. v1.4.0부터는 파일명이 `_hash8`(시각 suffix 포함 시 그 뒤까지)로 끝나 정규식 의도와도 맞지 않는다.
- **발생 조건:** OPDS 서버를 켜고 리더기나 OPDS 클라이언트에서 카탈로그를 본다.
- **영향:** `<summary>`에 `테크뉴스 2026-11-02 c070adea.epub (12 KB)`처럼 날짜·hash·확장자가 그대로 나온다. `<title>`은 원래도 파일명이다. 다운로드와 링크는 정상이다. 표시만의 문제다.
- **근거:** R1 출력.
- **반증 확인:** 이 값은 `<summary>` 표시에만 쓰이고, 경로나 링크 계산에는 쓰이지 않는다. 따라서 Low다.
- **호출/영향 범위:** `OPDSHandler.do_GET → _serve_catalog`.
- **권장 수정 방향:** 공백 치환 전에 `_(\d{4}-\d{2}-\d{2})(?:_[0-9a-f]{8})?(?:_\d{6}_\d{6})?\.epub$`처럼 현재 빌더 형식을 처리하고, 남은 이름에서 밑줄을 공백으로 바꾼다. `<title>`에도 정리한 사이트명과 날짜를 쓰는 것을 고려한다.
- **필요한 회귀 테스트:** `뉴스_2026-11-02_c070adea.epub`, `뉴스_2026-11-02_c070adea_174547_653761.epub`, `Daily_Digest_2026-11-02_1a2b3c4d.epub`, 옛 형식 `뉴스_2026-10-01.epub`의 카탈로그 summary가 각각 `뉴스`/`Daily Digest`(+날짜)로 표시되어야 한다.

## 5. Potential Functional Gaps

| 구분 | 내용 | 판단 |
|---|---|---|
| Likely Gap | AI 요약·번역 중 취소·종료 반응 지연 | 취소는 사이트 경계와 업로드 배치 앞에서만 확인한다(CLAUDE.md §3-3에 문서화됨). 요약은 기사당 최대 20초(OpenAI)·30초(Ollama), 번역은 요청당 10초 timeout이다. 기사가 많은 사이트를 처리하는 중이면 취소나 창 닫기가 수 분 동안 끝나지 않을 수 있다. `_on_close`는 의도적으로 무기한 기다린다(이력 commit 보호). 버그가 아니라 반응성 보완점이다. 기사 루프 안에서 `is_cancel_requested`를 확인하면 줄일 수 있다. |
| Likely Gap | 업데이트 헬퍼 기동 실패 후 재시도 수단 | `after_drain`의 `launch_update`가 실패하면(헬퍼 exe 복사가 백신·디스크 문제로 실패) 오류창을 띄운 뒤 그대로 창을 닫는다(`sync_control.py:266-277`). drain으로 서버·Watch가 이미 멈췄기 때문에 닫는 것 자체는 합리적이다. 재실행하면 정상 동작하고 staged 파일은 `cleanup_stale_artifacts`가 정리한다. 다만 사용자는 업데이트를 처음부터 다시 받아야 한다. |
| 추정 | 기기가 보고한 파일명의 Windows 특수 형식 | `list_files`는 `/`, `\`, `.`, `..`를 거르지만 `C:x.epub`(드라이브 상대 경로), `a.epub:stream`(ADS), `CON` 같은 이름은 거르지 않는다. 이런 이름이 `os.path.join(dest_dir, name)`에 들어가면 선택한 폴더 밖에 쓸 수 있다. 정상 CrossPoint(FAT/exFAT SD)는 `:`가 든 이름을 만들 수 없으므로, LAN의 악성 기기나 `crosspoint.local` 스푸핑이 전제다. 현재 버그로 분류하지 않았다. ISSUE-001을 고칠 때 `os.path.basename` + 금지 문자 검사를 함께 넣으면 해소된다. |
| 추정 | Linux `crontab -l`의 "crontab 없음" 외 실패 | 반환 코드가 0이 아니면 기존 crontab을 빈 문자열로 간주하고 관리 블록만 써 넣는다. 권한·데몬 문제로 읽기만 실패하면 사용자 cron 줄이 사라질 수 있다. `logs/cron.bak`에 (빈) 백업이 남지만 이 경우엔 의미가 없다. stderr의 `no crontab for` 여부로 구분하는 것이 안전하다. 재현하지 않았다. |
| 추정 | `load_config`의 자동 보강 저장이 revision을 올리지 않음 | `_normalize_loaded`가 기기 ID·토큰을 새로 만들면 `bump_revision=False`로 저장한다(`manager.py:352`). 다른 writer가 그 직전 revision으로 CAS 저장하면 충돌로 감지되지 않는다. GUI는 저장 직후 `_reload_config()`로 같은 프로세스에서 바로 ID를 부여·반영하므로, 실제 경합 창은 수동 편집이나 구버전 설정을 두 프로세스가 동시에 처음 읽는 경우뿐이다. 영향(새 ID로 이력 키가 갈라짐)은 크지만 발생 조건이 매우 좁다. |
| Confirmed Gap | 원격 전송 receipt(응답 유실 조정) | 업로드 응답이 유실되면 이력이 기록되지 않아 다음 실행에서 같은 기사가 다시 간다. 같은 PC에서는 로컬 파일이 남아 있어 시각 suffix가 붙으므로 기기에 중복 책이 생긴다. 이미 문서화된 범위 밖 기능이다(CLAUDE.md 2026-10-21 절). |
| Confirmed Gap | PC 간 exactly-once 전송 | 공유 폴더 락과 replica는 분산 lease가 아니다. 문서화된 제약이다. |

## 6. Documentation Mismatches

1. **`AGENTS.md`가 CLAUDE.md보다 오래됨(미추적 파일):** `git status`에서 `?? AGENTS.md`다. CLAUDE.md와 비교하면 다음 내용이 현재 구현과 다르다.
   - §3-4 네이버: "이미지 제거: 모든 `img` 태그 decompose" → 실제로는 `include_images`가 켜져 있으면 EPUB 내부 리소스로 포함한다.
   - §3-5 파일명: `{site_name}_{YYYY-MM-DD}.epub` → 실제 `{사이트}_{날짜}_{hash8}.epub`.
   - §3-6 업로드 파일명: "영숫자·하이픈·언더바만 허용" → v1.3.6부터 한글 등 원래 문자를 유지한다.
   - §3-9 notifier: "윈도우 BalloonTip" → 실제로는 크로스플랫폼이다.
   - 2026-10-13 이후 감사 계약 절(설정 복구, `source_id`, Watch 큐, 업데이터 이동식 교체, 프리셋 카테고리 등)이 없다.
   AGENTS.md를 읽는 다른 에이전트·도구가 옛 규칙(ASCII 전송명 등)으로 코드를 되돌릴 수 있다. CLAUDE.md와 동기화하거나 CLAUDE.md를 가리키는 짧은 파일로 바꾸는 것을 권한다.
2. **`websync/upload/sync_epub.py:8` 주석:** "site_YYYY-MM-DD.epub, Daily_Digest_YYYY-MM-DD.epub"는 `hash8` 이전 형식이다. 파서는 마지막 `YYYY-MM-DD`를 읽으므로 동작은 맞다. 주석만 다르다.
3. **OPDS summary 제목(ISSUE-003):** 코드 의도(날짜·확장자 제거)와 실제 동작이 다르다.

README.md, README.ko.md, docs/USER_GUIDE.md, docs/DEVELOPER.md의 파일명 규칙(원래 문자 유지, `hash8`, 로마자 변환 제거), CI 구성(Linux 3.15 전체 + Windows 3.10 계약 테스트 16개 파일), 스크래퍼 13종, `romanize.py` 삭제는 실제 구현과 일치한다. 지난 감사의 문서 불일치 4건은 모두 해소되었다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 기기 파일 다운로드 전에 로컬 충돌을 확인하고, 기본은 이름을 바꿔 저장한다. 덮어쓰기는 명시적으로 고를 때만 한다. 기기가 보고한 이름은 `basename` + Windows 금지 문자·드라이브 접두사·ADS 검사로 정리한다. 완료 조건: R2 시나리오에서 원본 bytes가 보존된다.

Critical·High 수준의 데이터 손상이나 동시성 문제는 발견하지 못했다. Phase 1은 이 한 항목이다.

### Phase 2 — Stability

1. **ISSUE-002:** 세 플랫폼 스케줄러 모두 실패 시 stderr/stdout을 `last_error`와 로그에 남긴다. Windows 출력 디코딩을 시스템 코드 페이지 기준으로 바꾼다.
2. 요약·번역 기사 루프 안에서 취소를 확인해 종료·취소 반응 시간을 줄인다. 이미 처리한 기사는 버리고 이력은 남기지 않는 기존 계약은 유지한다.
3. Linux `crontab -l` 실패를 "crontab 없음"과 구분해, 읽기 실패 시에는 등록을 중단한다.
4. `load_config`의 자동 보강 저장도 revision을 올리거나, ID·토큰 생성은 `update_config` RMW 경로에서만 하도록 한다.

### Phase 3 — Structural

1. **ISSUE-003** 포함: EPUB 파일명 생성·파싱 규칙(빌더, `sync_epub` 날짜 파서, OPDS 제목)을 한 모듈로 모아, 형식이 바뀔 때 함께 바뀌게 한다.
2. 원격 전송 receipt 모델(산출물 이름·hash ↔ 기사 이력)을 검토한다. 응답 유실 조정과 기기 중복 책 정리의 기반이 된다.
3. AGENTS.md를 CLAUDE.md에서 생성하거나 링크로 대체해 지침 문서를 하나만 정본으로 둔다.

위 내용은 권고이며 코드는 변경하지 않았다.

## 8. Test Recommendations

| 계층 | 입력 조건 | 기대 결과 |
|---|---|---|
| Unit — ISSUE-001 | 폴더에 `book.epub`(bytes `A`) 존재, fake `/download` 200 응답 bytes `B`, 기본 정책 | `book.epub`는 `A` 유지, `book (1).epub`가 `B`. 결과에 "이름 바꿔 저장 1건" |
| Unit — ISSUE-001 | 같은 조건, 사용자 선택 "덮어쓰기" | `book.epub`가 `B`, `.part` 잔재 없음 |
| Unit — ISSUE-001 | 기기 목록 응답에 `C:evil.epub`, `a.epub:x`, `CON.epub` | `list_files`가 건너뛰거나 다운로드가 선택 폴더 안의 안전한 이름으로만 저장 |
| Integration — ISSUE-001 | 3개 파일 일괄 다운로드, 그중 1개만 충돌 | 확인 1회, 나머지 2개는 묻지 않고 저장, 결과 대화상자에 충돌 처리 내역 |
| Unit — ISSUE-002 | `subprocess.run` → `returncode=1`, `stderr="ERROR: Access is denied."` | `register_daily_task()` False, `last_error`에 해당 문구, logger warning 1회 |
| Platform — ISSUE-002 | macOS `launchctl load` 실패, Linux `crontab -` 실패 각각 | 같은 방식으로 `last_error`가 채워짐 |
| Unit — ISSUE-003 | 신·구 형식 파일 4종이 있는 output 폴더로 `/opds` 요청 | 각 `<summary>`가 정리된 사이트명(+날짜)으로 시작, `.epub`·hash 없음 |
| Concurrency — 취소 반응 | 요약이 켜진 사이트 1개(기사 10개, fake 요약 각 2초) 실행 중 1초 뒤 `request_cancel` | 3초 이내에 `status=cancelled`, 업로드·`mark_synced_many` 0회 |
| Regression — 종료·업데이트 | `after_drain`에서 `launch_update_helper`가 `OSError` | 오류창 1회, `root.destroy` 호출, staged 파일은 다음 기동의 `cleanup_stale_artifacts`가 제거 |
| Platform — crontab | `crontab -l` → `returncode=1`, stderr `"permission denied"` | 등록 중단, 기존 crontab 미변경, `last_error` 설정. `no crontab for user`일 때만 새로 생성 |
| Concurrency — 설정 | 장치 ID 없는 설정 파일에서 프로세스 A `load_config`(ID 부여 저장) 직전 revision으로 프로세스 B가 `save_config(expected_revision=r)` | B가 `ConfigConflictError`를 받거나, 병합 후 A가 부여한 ID가 디스크에 남아야 함 |
| E2E — 핵심 흐름 회귀 | fake CrossPoint 2대, 공유 이력, 같은 날 PC A(기사 1~3)·PC B(기사 4~5) 전송 | 기기마다 파일 2개(서로 다른 `hash8`), 이력 각 1회. 기존 `test_multi_pc_pipeline.py`에 `hash8` 고유성 assert 추가 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | **Good** | 전체·선택·합본·EPUB만 만들기 흐름이 같은 배치·기록 헬퍼를 공유하고, 기기별 alias 판정이 `needs_sync`와 배치 그룹에서 일치한다. 남은 기능 결함은 다운로드 충돌(ISSUE-001)과 표시 문제(ISSUE-003)다. |
| Runtime Stability | **Good** | 스레드·프로세스 락, 작업 수락 시 취소 초기화, Tk를 유지하는 종료 drain, 업데이트 적용 전 실행 중 작업 확인, 확인한 네트워크 호출(스크래퍼·업로드·기기 API·요약·번역·업데이트)의 timeout을 확인했다. |
| Data Integrity | **Good** | 원자적 저장, 구조 검증, revision CAS, SQLite 트랜잭션·PK, tombstone, 성공 기기만 기록. 유실 경로는 ISSUE-001의 로컬 파일 1개 범위뿐이다. |
| Error Resilience | **Acceptable** | 파이프라인·백업·업데이트는 실패를 상태와 결과로 보고하고 롤백한다. 스케줄러 실패 원인 노출(ISSUE-002)과 요약·번역 중 취소 반응은 보완이 필요하다. |
| Cross-platform Robustness | **Acceptable** | Windows 경로·업데이터·락은 잘 다뤄졌고 Windows CI 계약도 있다. schtasks `cp949` 고정, crontab 읽기 실패 구분, 기기 파일명의 Windows 특수 형식 처리가 남았다. macOS/Linux 실제 환경은 검증하지 않았다. |
| Test Confidence | **Good** | 703개 테스트가 실패 회복·다중 PC·업데이트 교체·HTTP 계약을 다룬다. 다운로드 성공 시 충돌, 스케줄러 stderr, OPDS 제목은 테스트가 없다. 라이브 프리셋 27건은 네트워크가 있어야 실행된다. |

### 먼저 수정할 문제 3개

1. **ISSUE-001** — 기기 파일 다운로드가 같은 이름의 로컬 파일을 경고 없이 덮어씀 (Medium, Confirmed)
2. **ISSUE-002** — 스케줄 등록 실패 사유(schtasks/launchctl/crontab stderr)를 사용자와 로그에 전달 (Low, Confirmed)
3. **ISSUE-003** — OPDS 카탈로그 제목 정리를 현재 EPUB 파일명 형식에 맞춤 (Low, Confirmed)
