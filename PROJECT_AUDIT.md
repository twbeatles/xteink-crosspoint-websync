# Project Audit

> 후속 개선: 2026-10-21 이 감사의 ISSUE-001~004와 충돌 병합·스케줄 명령 길이·dead code·문서 불일치 권고를 구현했다. 아래 이슈·평가는 감사 당시 기록이며 현재 미수정 목록이 아니다. 실기기의 같은 경로 업로드 의미·한글 파일명 검증과 원격 전송 receipt 모델은 남은 범위다. [구현 대조표와 검증 근거](docs/AUDIT_IMPLEMENTATION.md)를 참조한다.

> 감사일: 2026-10-21 (Asia/Seoul) · 기준: `main`, `5caebe49534cb810d3852c05f22134df74e95abc` (v1.3.7)
>
> 기능 구현·런타임 안정성 감사. 애플리케이션·테스트 코드는 변경하지 않았고 이 보고서만 새로 작성했다. 이전 감사(2026-10-15, `78ab384`)의 ISSUE-001~003은 후속 커밋에서 수정되었음을 코드로 다시 확인했다(저장 전 구조 검증, 원본 basename hash, `source_id` 기반 합본 누적). 아래 이슈 번호는 이번 감사에 한정한다. 이전 기록은 [docs/AUDIT_IMPLEMENTATION.md](docs/AUDIT_IMPLEMENTATION.md)에 있다.

## 1. Executive Summary

전체 상태는 **Acceptable(일부 Needs Work)**, 전체 위험도는 **Medium**이다. 핵심 경로(수집 → 기기별 중복 판정 → EPUB → 업로드 → 성공 기기만 이력 기록)는 일관되게 구현되어 있다. 설정 저장 전 구조 검증, SQLite 트랜잭션·복합 PK, 작업 락·취소, Watch 영속 재시도 큐, 대시보드 인증 등 방어도 충분하다. 전체 테스트 651 passed / 1 skipped.

이번 감사에서 반증되지 않고 남은 문제는 다음 4개다. Critical은 없다.

| 이슈 | 심각도 / 신뢰도 | 요약 |
|---|---|---|
| ISSUE-001: 같은 날 다른 PC(또는 다른 출력 폴더)에서 만든 EPUB이 동일한 원격 파일명을 사용 | High / Likely (이름 충돌은 Confirmed, 기기 측 덮어쓰기는 미검증) | 다중 PC 공유 이력으로 "새 글만" 보낸 저녁 EPUB이 아침 EPUB과 같은 경로로 업로드되어, 이미 완료로 기록된 기사가 기기에서 사라질 수 있음 |
| ISSUE-002: 업데이트 적용이 Tk 콜백 안에서 `sys.exit(0)`을 호출해 정상 종료 drain을 우회 | Medium / Confirmed (흐름), Likely (영향) | 진행 중 동기화·Watch 대기 이벤트·예약된 백업 push가 정리 없이 중단됨 |
| ISSUE-003: 선택 전송이 취소·예외로 끝나면 이미 기록한 이력을 공유 폴더에 push하지 않음 | Low / Confirmed | 다른 PC가 같은 기사를 다시 보낼 수 있음. 전체 동기화는 같은 상황에서 push함 |
| ISSUE-004: 설정 복구(`restore_config`)가 앱이 정상 로드하는 설정을 경고 때문에 거부 | Low / Confirmed | 손상 시 `.bak` 복구가 막히고 수동 JSON 편집이 필요함 |

**데이터 손상·유실 가능성:** SQLite 이력과 `config.json` 자체가 손상될 경로는 찾지 못했다. ISSUE-001은 **기기에 있는 책의 유실** 가능성이다. 해당 기사는 이미 전송 완료로 기록되어 있어 자동으로 다시 보내지지 않는다. CrossPoint가 같은 경로 업로드를 대체한다는 가정은 앱 자체의 수동 업로드 "덮어쓰기 경고"와 같지만, 실기기에서는 검증하지 않았다. ISSUE-002·003은 중복 재전송이 생길 수 있는 상태 문제이며 유실은 아니다. 단, ISSUE-002에서 Watch의 미안정 이벤트는 사라질 수 있다.

**가장 먼저 수정할 영역:** 자동 업로드의 원격 파일명 고유성(ISSUE-001). 그다음은 업데이트 종료 경로를 `_on_close` drain과 통합하는 것이다(ISSUE-002).

## 2. Project Understanding

### 목적

CrossPoint 펌웨어를 쓰는 XTEINK X3/X4 e-ink 리더기용 데스크톱 동반 앱이다. 웹·RSS·블로그·뉴스레터·자막을 수집해 EPUB으로 만들고 기기의 HTTP `/upload`로 무선 전송한다. 이미 보낸 글은 기기별 SQLite 이력으로 제외한다. 여러 PC는 공유 폴더(`sites.json`, `synced_posts.json`, `.websync-replicas/`)로 구독과 이력을 공유한다. Calibre 서재·Watch 폴더 전송, 기기 파일 관리, OPDS, 웹 대시보드, 서명된 자동 업데이트도 제공한다. README, README.ko, CLAUDE.md, AGENTS.md, CONTRIBUTING 규칙(main 기본, Spec Kit opt-in)을 확인했다.

### 주요 entrypoint

| Entry point | 분기 |
|---|---|
| `x3_websync.py:72 main` | `--smoke`, `--apply-update`(헬퍼), `--check-update`, `--recover-config`, `--sync`(CLI), 기본 GUI(단일 인스턴스 락) |
| `gui/app_core/sync_control.py` | 즉시 동기화, 백그라운드 작업 추적, `_on_close` drain |
| `gui/sync_tab/preview.py` | 미리보기 → 선택 전송 / EPUB만 만들기 |
| `servers/dashboard/handler.py` | `/api/login`, `/api/sync`, `/api/cancel`, 상태·로그 |
| `gui/settings_tab/watch.py` + `watch/` | Calibre 폴더 감시 → 영속 재시도 큐 |
| `scheduler/manager.py` | schtasks / launchd / crontab → `--sync` |

### 핵심 모듈과 저장 방식

- `pipeline/service.py`(SyncService): 스레드 락 + 프로세스 파일 락, 작업 수락·취소, 백업 pull/push 훅, 결과 상태.
- `pipeline/sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py`, `sources.py`: 전체/선택/미리보기/파일 전용 흐름, URL 기반 `source_id`.
- `config/manager.py`, `validator.py`: `config.json` RMW(`update_config`), revision CAS, 저장 전 구조 검증, `.bak`·`.corrupt`·`.rejected.*` 보존.
- `db/history.py`: `synced_posts(url, device_ip)` PK, `deleted_posts` tombstone, 작업별 연결과 commit/rollback, WAL.
- `upload/uploader.py`, `device_client.py`, `device_ids.py`: 전송명 정리(+원본 basename MD5 6자리), 기기 안정 ID·alias 키.
- `backup/`: 공유 폴더 병합(사이트 URL·tombstone, 이력 합집합, 기기 ID 채택).
- `core/update/`: Ed25519 manifest, 크기·SHA256 스트리밍 검증, 헬퍼 교체·smoke·롤백.
- 외부 의존성: requests, bs4/lxml, ebooklib, customtkinter, cryptography(필수), Pillow, googletrans, youtube-transcript-api, watchdog, Calibre CLI(선택).

### 핵심 실행 흐름

1. **전체 동기화:** `GUI/CLI/Dashboard → SyncService._try_acquire_pipeline_locks → maybe_backup_pull → run_sync_pipeline_locked → ScraperFactory.fetch_articles → db.needs_sync(alias 키) → (번역/요약) → group_articles_by_pending_targets → EpubBuilder.build/build_digest → X3Uploader.upload_to_targets → collect_mark_entries → db.mark_synced_many → maybe_backup_push → bool·_last_pipeline_result·toast`
2. **미리보기·선택 전송:** `preview_articles(락·pull·수집·중복 판정, 기록 없음) → GUI 선택 → sync_selected_articles(pull → selected_source_groups → 기기별 배치 → build/upload/mark → push)`
3. **EPUB만 만들기:** `build_selected_epubs → 공통 락 → build/build_digest → 경로 반환`(전송·이력 없음)
4. **Watch:** `watchdog 이벤트 → CalibreWatcher 디바운스·안정 크기 → WatchRetryQueue.enqueue(save → config.pending_jobs) → run → 파이프라인 락 → upload_to_targets(미완료 대상만) → fingerprint 재확인 → 완료 저장/제거 또는 지수 backoff`
5. **종료:** `_on_close → prepare_shutdown → 서버·Watch 정지 → shutdown_pipeline 대기 → 백그라운드 작업 대기 → flush_backup_push → root.destroy`
6. **업데이트:** `manifest 서명 → 스트리밍 크기·SHA256 → askyesno → launch_update_helper(헬퍼 exe 복사·기동) → sys.exit(0)` → 헬퍼: 부모 종료 대기(15초) → 백업 → `os.replace` → `--smoke` → 실패 시 롤백 → 결과 파일 → 재기동

## 3. Audit Coverage & Limitations

### 확인한 모듈

- **CodeGraph MCP(`codegraph_explore`)로 소스와 호출 관계를 확인:** `WatchRetryQueue`·`CalibreWatcher`·`SettingsWatchMixin`; `ConfigManager.import_sites → update_config → _save_config_unlocked → _require_structure → validate_config_structure`, `restore_config`, `load_config`의 호출자(60곳); `SyncHistoryDb.needs_sync → is_synced_for_any_key → is_synced_for_device`, `mark_synced_many` 호출자(sync_pipeline/selected_sync); `group_articles_by_pending_targets`, `collect_mark_entries*`, `ip_to_history_key_map`의 호출자.
- **직접 열람(bash/grep)으로 보완:** `sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py`, `sources.py`, `service.py`, `epub/builder.py`, `uploader.py`, `device_client.upload_to_path`, `device_files/actions.py`(수동 업로드 덮어쓰기 경고), `x3_websync.py`, `gui/config_recovery.py`, `app_core/app.py`·`sync_control.py`·`helpers.py`·`config_sync.py`, `core/update/installer.py`·`service.py`, `cli/update_apply.py`, `settings_tab/updater.py`, `scheduler/manager.py`(Windows/macOS 등록), `servers/dashboard/handler.py`·`session.py`, OPDS 토큰 비교, 그리고 `78ab384..HEAD`의 변경 파일 목록.
- 테스트 중 `test_selected_sync.py`, `test_config_input_recovery.py`, `test_updater_gui.py`, `test_uploader_sanitize.py`의 관련 케이스를 읽고 커버리지 공백을 확인했다.

### 실행한 검증

환경: **Windows 11 / Python 3.15.0**.

```text
python -B -m pytest tests/ -q --tb=short -ra -p no:cacheprovider
651 passed, 1 skipped in 110.82s (0:01:50)
exit code: 0
skip: tests/test_storage_isolation.py:121 — POSIX directory descriptors
```

저장소에 파일을 추가하지 않고 일회성 Python 재현을 실행했다. 모두 import 전에 `X3_WEBSYNC_STORAGE_ROOT`를 세션 임시 폴더로 지정했다(재현 3에서 `PROJECT_ROOT`가 임시 경로임을 출력으로 확인).

| 재현 | 결과 |
|---|---|
| R1: 서로 다른 출력 폴더(PC A/B 가정)의 `EpubBuilder("뉴스")`, 같은 날 다른 기사 | 로컬 `뉴스_2026-10-21.epub` ×2, 전송명 모두 `뉴스_2026-10-21_443afb.epub`. 합본도 둘 다 `Daily_Digest_2026-10-21_3bd71d.epub` |
| R2: dashboard port 80 + item_selector 빈 CSS 사이트 설정 | `load_config` 성공(경고 2건 로그). 본 설정을 구조 손상시킨 뒤 이 파일로 `restore_config` → `ConfigLoadError`로 거부 |
| R3: 선택 전송, 첫 기기 배치 업로드 성공 직후 취소 | `mark_synced_many` 1회, `maybe_backup_push` 0회. 비교: `_run_pipeline_body`는 파이프라인 실패/취소 후에도 push 1회 |
| R4: 최소 Tk 스크립트에서 `after` 콜백이 `sys.exit(0)` | `SystemExit`이 mainloop 밖으로 전파, `WM_DELETE_WINDOW` 핸들러 미실행, daemon 작업 미완료로 즉시 종료 |

### 한계

- 실제 X3/X4와 CrossPoint 펌웨어가 없어, 같은 경로 업로드가 대체·거부·별도 저장 중 무엇인지 확인하지 못했다(ISSUE-001의 핵심 가정). 한글 multipart 파일명의 펌웨어 표시·안정성도 확인하지 못했다.
- 실제 업데이트 헬퍼(frozen EXE)는 실행하지 않았다. ISSUE-002는 코드 흐름과 최소 Tk 재현에 근거한다.
- 외부 사이트·AI/번역 provider·Calibre·클라우드 동기화 클라이언트, macOS/Linux native 스케줄러·GUI, 원격 CI 결과는 확인하지 않았다.
- CodeGraph는 AST 기반 정적 분석이다. 동적 연결(Tk 콜백, 스레드 target)은 소스를 직접 읽어 판단했다. 모든 분기를 검증하지는 않았다. 백업 병합 세부(`backup/service.py`, `format.py`)는 기존 테스트(interleavings, crash consistency)가 넓어 이번에는 호출 경계만 확인했다.
- 사용자 `config.json`·`sync_history.db`를 열거나 수정하지 않았고 의존성을 설치하지 않았다.

## 4. High-Risk Issues

### [ISSUE-001] 같은 날 다른 PC·출력 폴더에서 만든 EPUB이 동일 원격 경로로 업로드됨

- **위치:** `websync/epub/builder.py:75 EpubBuilder.build`(L84–90), `:156 build_digest`(L173–178); `websync/upload/uploader.py:41 X3Uploader._sanitize_filename`, `:162 upload_to_targets`.
- **우선순위:** High
- **신뢰도:** Likely. 원격 이름 충돌은 R1로 Confirmed이고, 기기에서 기존 책을 대체하는지는 미검증이다.
- **문제:** 로컬 파일명은 `{사이트명}_{YYYY-MM-DD}.epub`(합본은 `Daily_Digest_{날짜}.epub`)이고, **로컬 출력 폴더에 같은 파일이 있을 때만** 시각 suffix가 붙는다. 전송명 hash는 이 basename으로만 계산하므로 같은 basename은 항상 같은 원격 이름이 된다. 자동 파이프라인은 원격 존재 여부를 확인하지 않고 `/upload`로 보낸다.
- **발생 조건:** README가 안내하는 다중 PC 흐름이다. 데스크톱이 아침에 소스 X를 전송하고, 노트북(별도 `output_dir`, 공유 이력)이 같은 날 X의 새 글만 전송한다. 같은 `default_upload_path`(기본 `/`)를 쓴다. 일간 합본 모드에서는 소스와 무관하게 같은 날 두 PC가 전송하면 항상 충돌한다. 한 PC에서도 같은 날 출력 폴더를 비우거나 `output_dir`을 바꾼 뒤 재전송하면 같은 일이 생긴다.
- **영향:** 펌웨어가 같은 경로를 대체하면 아침 EPUB(기사 1~3)이 저녁 EPUB(기사 4~5)으로 바뀐다. 기사 1~3은 이미 해당 기기에 `mark_synced`되어 있어 다시 전송되지 않으므로 사용자는 그 기사를 잃는다. 업로드는 HTTP 200으로 성공 처리되어 경고도 없다.
- **근거:** R1 출력. `uploader.py:44` 주석은 "충돌로 인한 덮어쓰기를 방지"를 의도하지만 hash는 결정적이라 동일 basename에는 효과가 없다. `gui/device_files/actions.py:301–329`의 수동 업로드는 `remote_file_exists`로 확인한 뒤 "덮어쓰기" 경고를 띄운다. 즉 앱 스스로 같은 이름 업로드를 대체로 간주한다.
- **반증 확인:** (1) builder의 존재 검사는 로컬 폴더에 한정되어 다른 PC·비운 폴더에는 적용되지 않는다. (2) `check_batch_filenames`는 수동 업로드 한 배치 안에서만 쓰이고 자동 파이프라인에는 적용되지 않으며, 서로 다른 실행 간에는 의미가 없다. (3) 공유 폴더는 `output_dir`을 내보내지 않는다(README 보안 안내). (4) 이력 DB는 기사 URL 단위라 원격 파일의 정체성을 추적하지 않는다. (5) README의 "같은 reader의 자동 전송 PC는 하나만"은 자동 스케줄 중복을 다룰 뿐, 다른 PC의 수동 동기화나 같은 PC의 폴더 정리는 막지 않는다. (6) `docs/AUDIT_VALIDATION.md:33`은 실기기 덮어쓰기 의미를 미검증 항목으로 남겨 두었고, 이 교차 실행 충돌 자체는 문서화된 제약이 아니다.
- **호출/영향 범위:** `run_sync_pipeline_locked(L215, L321) / sync_selected_articles(L150, L216) → build/build_digest → upload_to_targets → _sanitize_filename`. 같은 함수를 `DeviceClient.upload_to_path`와 Watch(`_attempt_watch_upload`)도 쓴다. Calibre 서재에서 파일명이 같은 서로 다른 책에도 같은 구조가 적용된다.
- **권장 수정 방향:** 자동 생성 EPUB 전송명에 실행 단위 고유값(시각 suffix 또는 기사 URL 집합의 hash)을 항상 포함한다. 또는 업로드 전에 `remote_file_exists`로 확인하고 충돌 시 새 이름을 쓴다. EPUB identifier도 같은 기준으로 고유화한다. 기존 기기 파일은 자동으로 이관하거나 삭제하지 않는다.
- **필요한 회귀 테스트:** 서로 다른 `output_dir`을 가진 두 서비스가 같은 이력 DB(또는 공유 이력)를 쓰고, 같은 날 같은 소스에서 서로 다른 새 기사를 fake CrossPoint로 전송한다. 원격 key가 2개이고 두 bytes가 모두 보존되어야 한다. 합본 모드와 출력 폴더를 비운 뒤 재실행하는 경우에도 같은 결과여야 한다.

### [ISSUE-002] 업데이트 적용이 Tk 콜백에서 `sys.exit(0)`으로 종료해 graceful shutdown을 우회

- **위치:** `websync/gui/settings_tab/updater.py:256 _on_download_complete` → `websync/core/update/service.py:137 launch_update_and_exit`(L158 `sys.exit(0)`); 우회되는 `websync/gui/app_core/sync_control.py:233 _on_close`.
- **우선순위:** Medium
- **신뢰도:** 흐름은 Confirmed(코드 + R4). 데이터 영향은 Likely(frozen 실행 미재현).
- **문제:** 사용자가 "지금 적용"을 고르면 메인 스레드 콜백에서 헬퍼를 띄운 뒤 곧바로 `SystemExit`을 던진다. 이 예외는 mainloop를 빠져나가 `main()`의 `finally`(인스턴스 락 해제)만 실행하고 인터프리터를 종료한다. `prepare_shutdown`, 서버·Watch 정지(`retain`으로 대기 이벤트 보존), `shutdown_pipeline` 대기, 백그라운드 작업 대기, `flush_backup_push`가 모두 생략된다. 적용 전에 실행 중인 작업이 있는지도 확인하지 않는다.
- **발생 조건:** GUI 동기화나 대시보드 동기화, Watch 업로드가 진행 중일 때, 또는 사이트 저장 직후(1.5초 디바운스 push 대기 중) 업데이트를 적용한다.
- **영향:** daemon 파이프라인 스레드가 업로드 응답과 `mark_synced_many` 사이에서 끊기면, 기기에는 전송됐지만 이력이 없어 다음 실행에서 중복 전송된다(SQLite 트랜잭션은 원자적이라 DB 손상은 아님). Watch 관찰자의 디바운스·안정성 확인 중인 이벤트(`_pending`/`_checking`)는 `retain`되지 않아 사라지고, watchdog은 이벤트를 다시 보내지 않으므로 그 책은 자동 전송되지 않는다. 예약된 백업 push가 사라져 다른 PC가 최신 사이트 변경을 늦게 받는다.
- **근거:** R4에서 `after` 콜백의 `sys.exit(0)`이 `WM_DELETE_WINDOW` 핸들러를 거치지 않고 프로세스를 끝내는 것을 확인했다. `_make_background_thread`의 기본값은 `daemon=True`, `begin_sync_pipeline_async`도 `daemon=True`다. `_on_close`는 이와 대조적으로 non-daemon `app-shutdown` 스레드로 drain한다.
- **반증 확인:** 헬퍼는 부모 종료를 최대 15초 기다리지만 이는 파일 교체를 위한 것이지 작업 완료 대기가 아니다. Watch의 `pending_jobs`는 이미 큐에 넘어간 작업만 보존하고, 큐 이전 단계의 이벤트는 `stop()→retain` 경로에서만 보존된다. 테스트 `test_updater_gui.py:74`는 `launch_update_and_exit` 호출만 검증하며, 이 서비스는 Mock이다.
- **호출/영향 범위:** `SettingsUpdaterMixin._on_download_complete → UpdateService.launch_update_and_exit → launch_update_helper`. 영향 모듈: pipeline(service/sync_pipeline/selected_sync), watch, backup push 타이머.
- **권장 수정 방향:** 적용 확인 시 실행 중 작업이 있으면 거절하거나 대기를 안내한다. 헬퍼를 기동한 뒤에는 `sys.exit` 대신 `_on_close()`와 같은 drain을 거쳐 `root.destroy()`로 끝낸다. 헬퍼의 부모 대기 시간은 drain 시간을 고려해 늘리거나, drain이 끝난 다음에 헬퍼를 기동한다.
- **필요한 회귀 테스트:** fake 파이프라인 스레드가 업로드 직후 블록된 상태에서 업데이트 적용 경로를 호출하면 작업 완료(이력 commit)와 `flush_backup_push` 호출 뒤에만 종료해야 한다. Watch 디바운스 중인 경로는 종료 후 `pending_files`에 남아야 한다.

### [ISSUE-003] 선택 전송이 취소·예외로 끝나면 이미 기록한 이력을 공유 폴더에 push하지 않음

- **위치:** `websync/pipeline/selected_sync.py:20 sync_selected_articles`. 취소 반환 L131–139, L184–215, 예외 L277–279.
- **우선순위:** Low
- **신뢰도:** Confirmed(R3)
- **문제:** push는 정상 완료 경로(L257)에서만 호출된다. 취소는 기기 배치 사이에서 확인되므로, 첫 배치가 성공해 `mark_synced_many`로 기록된 뒤 취소되면 그 기록은 로컬 DB에만 남는다. 전체 동기화(`SyncService._run_pipeline_body`)는 파이프라인이 False를 반환해도 push한다.
- **발생 조건:** 공유 폴더(auto_export)를 켜고 여러 기기 또는 여러 소스에 선택 전송하다가 중간에 취소한다. 또는 한 소스의 빌드 예외로 중단된다.
- **영향:** 다음 push(다음 동기화, 사이트 변경 등)까지 공유 이력이 갱신되지 않는다. 앱을 그냥 닫으면 `flush_backup_push`는 타이머가 예약된 경우에만 실행되므로 push가 다음 세션까지 미뤄진다. 그 사이 다른 PC가 같은 기사를 다시 보낸다(중복, 유실 아님).
- **근거:** R3: mark 1회 / push 0회, 전체 파이프라인 비교 push 1회. GUI 호출부(`gui/sync_tab/preview.py:226`)도 보완 push를 하지 않는다(grep으로 `schedule_backup_push` 호출 위치 확인).
- **반증 확인:** `test_selected_sync.py:142`는 취소를 검증하지만 push를 `{"skipped": True}`로 고정해 호출 여부를 확인하지 않는다. 다음 push 때 전체 이력을 합집합으로 내보내므로 영구 불일치는 아니다. 그래서 Low로 분류했다.
- **호출/영향 범위:** `PreviewMixin → SyncService.sync_selected_articles → run_sync_selected_articles`, 영향: `backup/service.push`, 다른 PC의 `needs_sync`.
- **권장 수정 방향:** 락을 해제하기 전 `finally`에서, 이번 작업이 1건 이상 기록했다면 push를 시도한다(결과는 `_last_pipeline_result`에 반영). 또는 `schedule_backup_push()`를 예약한다.
- **필요한 회귀 테스트:** 두 기기 중 첫 배치 성공 후 취소하면 push가 1회 호출되고 status는 `cancelled`로 남아야 한다. 빌드 예외에서도 기록이 있으면 push가 시도되어야 한다.

### [ISSUE-004] `restore_config`가 앱이 정상 로드하는 설정을 의미적 경고 때문에 거부

- **위치:** `websync/config/manager.py:175 restore_config`(L184–186).
- **우선순위:** Low
- **신뢰도:** Confirmed(R2)
- **문제:** 복구 후보에 구조 검증(`_require_structure`)뿐 아니라 `validate_config`도 적용하고, 결과가 비어 있지 않으면 거부한다. `validate_config`는 `load_config`·`update_config`에서 **경고로만 로그하는** 의미 검사(포트 범위, CSS item_selector, 테마 등)다. CLAUDE.md의 2026-10-15 계약은 "의미적 warning과 기동 불가 구조 오류는 구분한다"고 적고 있다.
- **발생 조건:** `config.json`이 손상되어 GUI 복구 대화상자 또는 `--recover-config`를 쓰는데, `.bak`이나 선택한 파일에 경고 항목이 하나라도 있다(예: 이전 버전에서 저장된 CSS 사이트 선택자 누락, 범위 밖 포트). `update_config`는 경고가 있어도 저장하므로 이런 `.bak`은 앱이 직접 만들 수 있다.
- **영향:** 유일한 앱 내 복구 경로가 실패하고 기동도 막힌다(`offer_config_recovery`가 False → exit 1). 사용자가 JSON을 직접 고쳐야 한다. 원본·`.bak`은 보존되므로 데이터 손실은 없다.
- **근거:** R2: 같은 파일을 `load_config`는 경고 2건과 함께 로드하고, `restore_config`는 같은 두 메시지로 `ConfigLoadError`를 낸다.
- **반증 확인:** 테스트(`test_config_input_recovery.py:84`)는 구조적으로 잘못된 입력만 거부를 검증하며, 경고만 있는 정상 설정의 복구는 검증하지 않는다.
- **호출/영향 범위:** `x3_websync.main(--recover-config) / gui.config_recovery.offer_config_recovery → ConfigManager.restore_config`.
- **권장 수정 방향:** 복구 거부 조건을 구조 오류(`validate_config_structure`)로 제한하고, 의미적 경고는 복구 후 표시한다.
- **필요한 회귀 테스트:** 경고만 있는 설정 파일로 복구하면 성공하고 `load_config`가 동작해야 한다. 구조 오류 파일은 기존처럼 거부되고 원본·`.bak`이 바뀌지 않아야 한다.

## 5. Potential Functional Gaps

| 구분 | 내용 | 판단 |
|---|---|---|
| Confirmed Gap | 자동 업로드 전 원격 존재 확인·idempotency 없음 | ISSUE-001의 근본 원인과 같다. 응답 유실 후 완료 여부 조정(기존 문서의 공개 제약)도 같은 장치가 필요하다. |
| Likely Gap | GUI 저장 충돌 병합이 최상위 키 전체를 메모리 값으로 덮어씀 (`helpers.py:233 _merge_config_on_conflict`) | `calibre_watch`(Watch 워커가 백그라운드로 쓰는 `pending_jobs`), `x3_devices`/alias, `portable_data`가 stale 값으로 되돌아갈 수 있다. 같은 프로세스에서는 경합 창이 매우 좁다. 별도 `--sync` 프로세스의 pull 이후에는 다음 pull이 대부분 다시 수렴시킨다. 실제 손실은 재현하지 않았으며, 백그라운드에서 쓰는 필드는 디스크 값을 우선하는 필드별 병합이 안전하다. |
| 추정 | 한글 전송명 유지(v1.3.6)와 펌웨어 호환 | CLAUDE.md §9는 과거 "한글/공백 파일명 전송 → CrossPoint 크래시"를 기록하고 있다. 현재 코드는 한글을 유지한다. 최신 펌웨어에서 문제가 없는지 실기기로 확인할 필요가 있다. 결함으로 확정하지 않았다. |
| 추정 | Windows `schtasks /TR` 261자 제한 | `cmd.exe /c cd /d "<dir>" && "<pythonw>" "<script>" --sync` 형식이라 설치 경로가 길면 등록이 실패할 수 있다. 실패는 False로 보고되므로 조용한 오동작은 아니다. 재현하지 않았다. |
| Confirmed Gap | `upload/romanize.py`는 production 경로에서 더 이상 쓰이지 않음 | 테스트에서만 참조한다. dead code로, 위험이 아니라 정리 대상이다. |
| Confirmed Gap | PC 간 exactly-once 전송 | 공유 폴더 락·replica는 분산 lease가 아니다. 이미 문서화된 범위 밖 기능이다. |

## 6. Documentation Mismatches

1. **전송 파일명 규칙:** v1.3.6(`e24e08d`)부터 `_sanitize_filename`은 로마자로 바꾸지 않고 한글 등 원래 문자를 유지한다. 그러나 다음 문서는 아직 ASCII/로마자 변환을 설명한다.
   - `CLAUDE.md` §3-6 표("ASCII 전송명: 한글 prefix 로마자 표기"), 2026-10-13 절("ASCII와 원래 basename hash"), 2026-10-15 절("로마자 변환 전에 계산")
   - `README.ko.md:284` ("로마자 변환 전 원본 이름으로 hash")
   - `docs/USER_GUIDE.md:410` ("네이버뉴스 → neibeonyuseu")
   - `docs/DEVELOPER.md:298` ("변환 전 basename 기준")
   - `README.md:280`(원래 문자 유지)만 실제와 일치한다.
2. **존재하지 않는 테스트 참조:** `docs/DEVELOPER.md:286`은 `test_sanitize_filename_keeps_romanized_site_name`을 회귀 테스트로 적었지만 실제 이름은 `test_sanitize_filename_keeps_original_site_name`이다.
3. **uploader 주석:** `uploader.py:44`의 "충돌로 인한 덮어쓰기를 방지"는 같은 basename에 대해서는 성립하지 않는다(ISSUE-001).
4. **CLAUDE.md §3-9:** notifier를 "윈도우 BalloonTip"으로만 설명한다. 실제로는 크로스플랫폼이다(Windows 경로는 BalloonTip). 영향이 적은 서술 차이다.

이전 감사의 requirements.txt googletrans 주석 불일치는 해소되었다(`>=4.0.2,<5`). CI 구성(Linux 3.15 전체, Windows 3.10 계약 테스트 목록)은 CLAUDE.md 설명과 일치한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 자동 생성 EPUB의 원격 이름을 실행 단위로 고유화하거나 업로드 전 원격 존재를 확인한다. EPUB identifier도 함께 고유화한다. 완료 조건: 두 출력 폴더·같은 날·같은 소스 전송에서 fake 기기에 두 파일이 남는다.
2. **ISSUE-002:** 업데이트 적용을 `_on_close` drain에 통합하고, 실행 중 작업이 있으면 적용을 미룬다.

### Phase 2 — Stability

1. **ISSUE-003:** 선택 전송의 취소·예외 경로에서 기록이 있으면 push한다(전체 동기화와 동일한 계약).
2. **ISSUE-004:** 복구 거부를 구조 오류로 제한한다.
3. 충돌 병합을 필드별로 바꾼다. 백그라운드 writer 필드(`calibre_watch.pending_*`, 기기 alias)는 디스크 우선으로 한다.
4. 실기기에서 덮어쓰기 의미와 한글 파일명 호환을 `docs/AUDIT_VALIDATION.md` 절차로 기록한다.

### Phase 3 — Structural

1. 원격 산출물 정체성(이름·hash)을 기사 이력과 연결하는 모델(예: 전송 receipt 테이블)을 검토한다. 응답 유실 조정의 기반이 된다.
2. "작업 종료" 경로(정상 종료, 업데이트, 서버 재시작)를 하나의 shutdown 서비스로 묶어 테스트 가능하게 한다.
3. 문서의 파일명 규칙을 한 곳(DEVELOPER.md)에 정본으로 두고 나머지는 링크로 대체한다.

위 내용은 권고이며 코드는 변경하지 않았다.

## 8. Test Recommendations

| 계층 | 입력 조건 | 기대 결과 |
|---|---|---|
| Unit — ISSUE-001 | 같은 사이트명·같은 날짜, 서로 다른 `output_dir` 두 builder → `_sanitize_filename` | 서로 다른 전송명. 같은 실행 내 재호출은 결정적 |
| Integration — ISSUE-001 | loopback fake CrossPoint(같은 경로 PUT은 대체), 공유 이력 DB, PC A 기사1~3 → PC B 기사4~5 | 기기에 2개 파일, 기사1~5 본문 모두 존재. 이력은 각 1회 |
| End-to-End — ISSUE-001 | daily_digest 모드에서 위와 동일 | 합본 2개 보존. 두 번째 실행 후 첫 합본 bytes 불변 |
| Regression — ISSUE-001 | 한 PC에서 출력 폴더를 비운 뒤 같은 날 재동기화 | 기존 원격 파일과 다른 이름 |
| Unit — ISSUE-002 | 업데이트 적용 콜백 호출 시 `_job_active` 설정 상태 | 적용 거부 또는 대기 안내. 헬퍼 미기동 |
| Concurrency — ISSUE-002 | 업로드 성공 직후 블록된 fake 파이프라인 + 적용 요청 | 이력 commit·`flush_backup_push` 이후에만 종료 |
| Integration — ISSUE-002 | Watch 디바운스 중(2초 이내) 적용 | 재기동 후 해당 경로가 `pending_files`에 있고 전송됨 |
| Unit — ISSUE-003 | 2기기, 첫 배치 성공 후 `request_cancel` | `mark_synced_many` 1회, push 1회, status `cancelled` |
| Unit — ISSUE-003 | 두 번째 소스의 `build`가 예외 | 첫 소스 기록 후 push 시도, 예외는 그대로 전파 |
| Unit — ISSUE-004 | 경고만 있는 설정(port 80, CSS 선택자 누락)으로 `restore_config` | 성공. 원본은 `.rejected.*`로 보존, `.bak` 불변 |
| Regression — ISSUE-004 | `{"sites": null}` 등 구조 오류 | 기존처럼 거부, 파일 불변 |
| Concurrency — 설정 병합 | GUI `_save_ui_settings` snapshot 이후 Watch가 `pending_jobs` 추가 → CAS 충돌 | 병합 결과에 새 job 유지 |
| Platform-specific — Windows | 250자 이상 설치 경로에서 `register_daily_task` | 명확한 실패 메시지 또는 짧은 래퍼 사용으로 등록 성공 |
| Device E2E | 실기기에 한글 사이트명 EPUB, 같은 이름 재업로드 | 파일 목록 표시·열람 정상. 대체/거부 동작 기록 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 핵심 흐름과 다중 기기 판정은 정확하다. 교차 실행 원격 파일명 충돌(ISSUE-001)이 남아 있다 |
| Runtime Stability | Acceptable | 락·취소·종료 drain·Watch backoff가 견고하다. 업데이트 종료 경로만 예외다(ISSUE-002) |
| Data Integrity | Needs Work | 로컬 DB·설정 무결성은 양호하다. 기기 측 책 유실 가능성(ISSUE-001)과 공유 이력 지연(ISSUE-003)이 있다 |
| Error Resilience | Acceptable | HTTP 오류 변환, 백업 fail-closed, 업데이트 롤백이 있다. 복구 경로 과잉 거부(ISSUE-004)가 있다 |
| Cross-platform Robustness | Acceptable | OS별 adapter와 경로 처리, Windows 전체 테스트 통과. macOS/Linux native는 미검증 |
| Test Confidence | Good | 651 passed / 1 skipped. fixture·loopback·concurrency 범위가 넓다. 교차 PC 파일명·업데이트 종료·선택 취소 push 케이스는 비어 있다 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 같은 날 다른 PC·출력 폴더에서 만든 EPUB이 기기의 기존 책을 대체하지 않도록 원격 파일명을 고유화한다.
2. **ISSUE-002:** 업데이트 적용을 정상 종료 drain에 통합해 진행 중 전송·Watch 이벤트·백업 push를 보존한다.
3. **ISSUE-003:** 선택 전송이 취소·실패로 끝나도 기록한 이력을 공유 폴더에 push한다.
