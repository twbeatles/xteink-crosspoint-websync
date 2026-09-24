# Project Audit

감사일: 2026-09-24 (Asia/Seoul)
기준: main, a07dec4, v1.2.3, 감사 시작 시 깨끗한 작업트리
범위: 기능 구현, 런타임 안정성, 데이터 무결성, 복구 및 기능 관련 보안. 제품 코드는 수정하지 않았다.

> **후속 수정 상태 (2026-09-24):** 아래 1~9절은 수정 전 감사 스냅샷이다. v1.2.4에서 ISSUE-001~003을 수정하고 실패 경로 회귀 테스트를 추가했다. 공유 이력 pull 실패 시 전송을 중단하고 push 실패를 동기화 실패로 보고하며, 부분 게시 결과 표시, 기기 배치 사이 취소 확인, 공유 데이터 설명도 반영했다. 전체 테스트 최종 재실행 결과는 **341 passed**, `--smoke`는 정상이다. 이 과정에서 웹 대시보드와 OPDS의 로컬 HTTP 테스트가 일부 전체 실행에서 Windows 연결 재설정으로 실패했으나, 해당 파일 단독 실행과 전체 재실행은 통과했다. 릴리스 전 재확인에서 수정 전 HEAD(a07dec4)의 깨끗한 worktree도 같은 로컬 연결 재설정 실패를 보여, 이번 변경과 무관한 환경 요인으로 판단한다. 원인은 특정하지 못했으며 실제 기기·클라우드·macOS/Linux 검증도 남아 있다.

## 1. Executive Summary

전체 상태는 **주요 기능과 정상 경로의 테스트가 양호하지만, 실패 경로에는 수정이 필요**하다. 전체 위험도는 **High Risk**로 평가한다. 공유 폴더 이력을 정본으로 사용하는 다중 PC 환경에서 로컬 DB 병합이 실패하면 원격 전용 전송 이력을 공유 파일에서 제거하면서 성공으로 보고하는 경로를 격리 환경에서 재현했다. 일반적인 동기화 경로의 업로드 성공 후 이력 기록, SQLite 트랜잭션, 프로세스 락은 확인했으며 그 자체를 이슈로 보지 않는다.

가장 중요한 문제는 다음 세 가지다.

1. **ISSUE-001 (High, Confirmed):** 공유 이력 병합 실패 뒤 원격 전용 기록을 누락한 파일을 성공적으로 다시 게시한다. 공유 정본의 데이터 유실 가능성이 있다.
2. **ISSUE-002 (Medium, Confirmed):** GUI 설정 저장이 거부되어도 즉시 동기화가 시작된다. 사용자가 방금 입력한 기기 주소나 옵션과 다른 저장 설정으로 실행될 수 있다.
3. **ISSUE-003 (Medium, Confirmed):** 동기화·프리뷰 워커의 예외가 완료 콜백을 건너뛰어 GUI 동기화 버튼을 비활성 상태로 남긴다.

**데이터 손상/유실 가능성:** ISSUE-001에서 공유 폴더의 유효한 synced_posts.json 일부가 원자적으로 *잘못된 합집합*으로 교체된다. 해당 기록을 가진 다른 PC가 남아 있으면 이후 복원될 수 있지만, 그 보장은 없다. 로컬 SQLite 파일이 이 재현에서 손상된 것은 아니다. 가장 먼저 수정할 영역은 websync/backup/service.py의 이력 병합 실패 처리다.

## 2. Project Understanding

이 앱은 CrossPoint 펌웨어를 쓰는 XTEINK X3/X4용 데스크톱 동반 프로그램이다. RSS·웹·YouTube 콘텐츠를 수집해 EPUB으로 만들고 Wi-Fi로 전송하며, Calibre·로컬 책 전송, 기기 파일 관리, 예약 실행, OPDS, 웹 대시보드, 공유 폴더 백업을 제공한다. README.md, CLAUDE.md, docs/DEVELOPER.md, 의존성·빌드 설정과 현재 코드를 대조했다. 저장소의 AGENTS.md 파일은 없으며, 이 감사에 주어진 AGENTS.md 지침은 적용했다.

- **Entrypoint:** x3_websync.py:47의 main. --sync는 헤드리스 파이프라인, 기본 실행은 CustomTkinter GUI, --smoke는 import·언어 카탈로그 점검, --check-update와 --apply-update는 업데이트 경로다.
- **핵심 모듈:** websync/pipeline/service.py는 파이프라인 락과 조정, sync_pipeline.py는 전체 수집·전송, selected_sync.py와 preview.py는 선택 전송·미리보기다. scrapers/는 13종 소스 어댑터, epub/는 책 생성, upload/는 HTTP 전송·기기 파일 API, db/history.py는 기기별 이력, backup/는 공유 JSON 병합, config/manager.py는 설정 로드·검증·원자 저장을 맡는다.
- **데이터 저장:** config.json, sync_history.db(SQLite), output/*.epub, logs/는 기본적으로 앱 경로에 있다. 사용자가 output_dir와 공유 폴더를 따로 지정할 수 있다. 공유 폴더의 sites.json·synced_posts.json은 다중 PC 정본이고 로컬 DB는 그 복사본 겸 작업 이력이다.
- **외부 의존성:** requests, BeautifulSoup/lxml, ebooklib, CustomTkinter, cryptography, CrossPoint HTTP API, 선택 기능의 Pillow·googletrans·youtube-transcript-api·watchdog, Calibre CLI, GitHub 업데이트 엔드포인트. requirements.txt와 requirements-optional.txt를 확인했다.
- **핵심 흐름:** CLI main 또는 GUI sync_control._run_immediate_sync → SyncService.run_sync_pipeline → 스레드·프로세스 락 → 공유 폴더 pull → ScraperFactory.fetch_articles → URL 키·이력 필터 → 선택적 번역·요약 → 기기별 누락 기사 그룹 → EpubBuilder.build/build_digest → X3Uploader.upload_to_targets → 성공 기기만 SyncHistoryDb.mark_synced_many → 공유 폴더 push → 결과·로그·GUI 상태 갱신.
- **공유 상태와 변경점:** config.json은 ConfigManager의 revision 비교와 파일 락으로 갱신한다. SQLite synced_posts/deleted_posts는 DB 락과 트랜잭션으로 변경한다. 백업 서비스는 공유 폴더 락 아래 JSON을 읽고 원자 교체한다. GUI는 데몬 워커를 쓰고 root.after로 결과를 메인 스레드에 전달한다.

## 3. Audit Coverage & Limitations

CodeGraph MCP를 일반 코드 검색보다 먼저 사용해 main → SyncService → 전체/선택/프리뷰 파이프라인, 백업 push → SQLite import/export → 공유 JSON 쓰기, GUI 실행 → 워커 → 완료 콜백, 기기 파일 UI → X3DeviceClient, 대시보드 인증 → 비동기 시작, 스케줄러와 프로세스 락의 호출 관계를 추적했다. 관련 호출자·영향 범위는 각 이슈에 적었다. CodeGraph가 큰 함수 본문을 일부 생략한 부분은 해당 파일의 누락 범위만 직접 열람했다.

실제 확인한 영역은 x3_websync.py, websync/pipeline, backup, db, config, upload, scrapers/base.py, epub 연계, GUI app_core/sync_tab, 서버 핸들러, 스케줄러, 업데이트 설치 경로와 관련 테스트다. 정상 경로의 방어 장치도 확인했다: 성공 전송 대상에 한한 이력 기록, DB rollback, 설정·공유 JSON 원자 쓰기, 프로세스 락, 스크래퍼 URL/리다이렉트·크기·timeout 제한, 서버 토큰 인증, 기기 삭제에서 루트 경로 거부. 이것들을 버그로 계상하지 않았다.

**실행 결과:** python -m pytest -q → 324 passed in 23.79s (exit 0). python x3_websync.py --smoke → v1.2.3 smoke check OK (exit 0). 별도 임시 폴더와 mock 예외를 쓴 재현 두 종류를 실행했다: 공유 이력 병합 실패 시 원격 기록 누락, GUI 저장 실패·워커 예외 시 상태 전이. 이 재현은 테스트 파일로 저장하지 않았다. 실제 기기·실제 클라우드 폴더·실제 사용자 데이터에는 접근하거나 변경하지 않았다.

**한계:** 실제 X3/X4 펌웨어의 HTTP 응답, Calibre 설치, AI/번역/YouTube 외부 서비스, GitHub 업데이트 배포, PyInstaller 실행 파일, macOS/Linux 스케줄러의 실제 등록·해제는 검증하지 못했다. 테스트는 이 Windows 환경에서만 실행했다. CodeGraph는 정적 호출 분석이므로 동적 콜백의 일부 경로와 외부 서비스 동작은 코드·격리 재현으로 보완했다. 별도 저장소 AGENTS.md는 존재하지 않는다.

## 4. High-Risk Issues

### [ISSUE-001] DB 병합 실패 뒤 공유 전송 이력을 축소해 다시 게시

- **위치:** websync/backup/service.py:450-510, BackupSyncService._push_unlocked
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 원격 posts/deleted_posts를 로컬 DB에 합치는 부분에서 SyncHistoryDbError가 나면 경고만 남기고, 병합 전 로컬 posts로 새 synced_posts.json을 작성한다. 마지막에는 result.ok도 True가 된다.
- **발생 조건:** 공유 파일에는 다른 PC에서만 생성된 이력이 있고, push 중 import_deleted_posts 또는 import_posts_union/재export가 SQLite 잠금·I/O 오류 등으로 실패한다.
- **영향:** 공유 정본에서 원격 전용 기록과 삭제 표식이 빠질 수 있다. 다른 PC의 로컬 DB가 남지 않으면 이력 복구가 어렵고, 이후 이미 전송한 글이 다시 전송될 수 있다. 삭제 표식이 사라진 경우 오래된 이력의 재등장도 가능하다.
- **근거:** 464-470행의 catch가 계속 진행하고, 471-478행이 로컬 스냅샷으로 공유 파일을 교체하며, 502행은 성공을 설정한다. 임시 폴더 재현에서 공유 파일의 원격 URL 1건과 로컬 URL 1건을 준비하고 DB import에 SyncHistoryDbError를 주입했다. 결과는 result_ok=True, history_written=True, remote_url_preserved=False, 게시 파일에는 로컬 URL만 있었다.
- **반증 확인:** 공유 폴더 락은 동시 쓰기만 직렬화하고, strict JSON reader는 입력 손상만 막는다. write_json_atomic은 파일 형식과 교체의 원자성을 지키지만 누락된 이력의 의미상 무결성은 보장하지 않는다. SQLite import의 트랜잭션/rollback도 실패 후 게시를 중지시키지 않는다. 정상 병합 테스트는 통과하나 이 오류 분기의 회귀 테스트는 없다.
- **호출/영향 범위:** CodeGraph 기준 BackupSyncService.push는 SyncService.maybe_backup_push, 예약 push, 수동 공유 동기화에서 호출된다. 이어지는 export_all_posts/import_posts_union → build_history_payload → synced_posts.json 경로가 영향 대상이다. 다른 PC의 pull·중복 제거가 이 파일을 소비한다.
- **권장 수정 방향:** 원격 이력 병합·재export가 실패하면 history 파일을 쓰지 말고 push를 실패로 반환한다. sites와 history를 묶은 일관성 상태 및 manifest 갱신 순서도 함께 검토한다.
- **필요한 회귀 테스트:** 임시 공유 폴더에 원격 전용 post와 tombstone, 로컬 DB에 다른 post를 둔다. import_posts_union과 import_deleted_posts 각각에 SyncHistoryDbError를 주입해 push.ok=False, 공유 history의 원본 바이트 불변, 원격 post/tombstone 보존을 확인한다.

### [ISSUE-002] GUI 설정 저장이 실패해도 이전 설정으로 즉시 동기화 시작

- **위치:** websync/gui/app_core/config_sync.py:114-169, AppConfigSyncMixin._save_ui_settings; websync/gui/app_core/sync_control.py:82-100, _run_immediate_sync
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** _safe_save_config가 검증 실패·쓰기 오류·revision 충돌로 False를 반환하면 _save_ui_settings는 단순 return으로 끝나며 호출자에 실패 여부를 전달하지 않는다. _run_immediate_sync는 반환을 확인하지 않고 워커를 시작한다. 파이프라인은 시작할 때 디스크 설정을 다시 로드하므로 이전 설정으로 진행한다.
- **발생 조건:** 사용자가 기기 주소나 출력 옵션을 바꾸고 즉시 동기화를 눌렀는데 검증 또는 config.json 저장이 실패한다. 특히 폰트 범위·포트 등 치명적 검증 실패나 쓰기 권한 문제에서 가능하다.
- **영향:** 저장 실패 경고와 별개로 전송이 시작되어 기존 기기에 보내거나 기존 옵션으로 EPUB을 생성할 수 있다. 사용자가 기대한 대상과 실제 대상이 달라지는 기능 오류다.
- **근거:** config_sync.py:163-164의 실패 분기는 값을 반환하지 않고, sync_control.py:83-100은 _save_ui_settings 호출 후 무조건 busy 설정·스레드 기동을 한다. 독립 모형에서 저장 실패를 반환하게 했을 때도 worker_started=1이었다.
- **반증 확인:** _safe_save_config는 오류 대화상자를 띄우지만 호출 중단 기능은 없다. SyncService._reload_config가 디스크 설정을 사용하므로 미저장 UI 값이 우연히 적용되는 보호도 없다. 파이프라인 락은 중복 실행만 막는다.
- **호출/영향 범위:** CodeGraph 경로는 GUI 즉시 동기화 버튼 → _run_immediate_sync → _save_ui_settings/_safe_save_config → SyncService.run_sync_pipeline → 디스크 설정 reload → uploader·builder다. CLI --sync에는 이 UI 저장 문제가 없다.
- **권장 수정 방향:** _save_ui_settings가 명확한 bool을 반환하고, 실패 시 즉시 동기화 기동을 중단한다. 저장 성공 뒤에만 busy 상태를 설정한다.
- **필요한 회귀 테스트:** 기기 주소를 A에서 B로 바꾼 UI에서 save_config를 실패시키고 동기화 버튼을 누른다. 워커 시작 0회, 업로드 0회, 화면 busy=False, 디스크 설정 A 불변을 확인한다.

### [ISSUE-003] GUI 파이프라인 예외 뒤 완료 콜백이 없어 버튼이 계속 비활성

- **위치:** websync/gui/app_core/sync_control.py:32-52, 82-115; websync/gui/sync_tab/preview.py:20-38, 120-140
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 전체·선택 동기화와 프리뷰 워커는 서비스 호출 뒤에만 root.after 완료 콜백을 예약한다. 서비스가 예외를 던지면 _make_background_thread의 finally는 스레드 추적 집합에서 제거만 하고 UI busy 해제를 예약하지 않는다.
- **발생 조건:** GUI가 열린 후 config.json이 손상·삭제되어 _reload_config가 실패하거나, 사이트별 catch 바깥의 설정/백업 준비 단계에서 예기치 않은 예외가 발생한다.
- **영향:** 실제 파이프라인 락은 finally로 해제되더라도 GUI 동기화·프리뷰 등 주요 버튼은 비활성으로 남는다. 앱 재시작이 사실상 복구 수단이 된다. 예외는 워커로만 전파되어 사용자에게 명확한 실패 상태도 전달되지 않는다.
- **근거:** sync_control.py:88-96과 preview.py:26-34, 129-136에서 완료 콜백은 서비스 호출 뒤에 있다. 인메모리 모형에서 워커의 RuntimeError를 주입하자 finished_callback_scheduled=0, ui_busy=True였다.
- **반증 확인:** sync_pipeline.py의 사이트별 예외 처리와 backup/service.py의 많은 catch는 일반적인 개별 실패를 처리하지만, 설정 reload·콜백 및 일부 준비 경로 전체를 감싸지 않는다. _make_background_thread의 finally는 UI 상태를 수정하지 않는다. SyncService의 락 release도 UI 상태와 독립이다.
- **호출/영향 범위:** CodeGraph 기준 GUI _run_immediate_sync → SyncService.run_sync_pipeline, SyncPreviewMixin.open_preview_window → preview_articles, _run_selected_sync_task → sync_selected_articles의 세 경로. 대시보드 비동기 시작은 별도 예외 처리 경로다.
- **권장 수정 방향:** 각 워커에 try/except/finally를 두고 예외를 기록·표시하며, 창이 살아 있으면 finally에서 메인 스레드 완료 콜백을 반드시 예약한다. 성공과 실패 결과는 구분해 표시한다.
- **필요한 회귀 테스트:** 세 워커에서 서비스가 RuntimeError 또는 ConfigLoadError를 던지게 한다. 각 경우 busy=False 복귀, 버튼 활성화, 오류 로그/표시, 추적 스레드 제거를 확인한다.

## 5. Potential Functional Gaps

- **Confirmed Gap — 실패 경로 테스트:** 324개 테스트는 모두 통과했지만 ISSUE-001의 DB 병합 실패 후 공유 파일 보존, ISSUE-002의 저장 실패 후 기동 차단, ISSUE-003의 워커 예외 후 UI 복구를 확인하는 테스트가 없다. 세 이슈의 회귀 테스트를 우선 추가해야 한다.
- **Likely Gap — 즉시 취소 체감:** 전체·선택 동기화는 사이트/배치 경계에서 취소를 확인한다. 긴 스크래핑, 번역, 요약, HTTP 업로드 도중에는 완료 또는 timeout까지 취소가 지연될 수 있다. 현재 계약이 “경계에서 중단”임을 확인했으므로 이것을 별도의 현재 버그로 분류하지 않는다. 취소 지연 요구가 있다면 요청별 제한 시간과 협조적 취소를 설계해야 한다.
- **추정 — 실제 펌웨어 호환성:** HTTP API 계약은 모의 응답 테스트가 중심이다. X3/X4 펌웨어 버전별 대용량 업로드, 이름 충돌, 삭제·이동 응답은 실제 기기로 확인해야 한다. 현재 코드 버그로 단정하지 않는다.

## 6. Documentation Mismatches

- README.md의 File Storage & Privacy 문단은 클라우드 공유 시 “device IPs ... strictly excluded”라고 설명한다. 그러나 websync/backup/device_registry.py:32-60, 174-180은 설정된 기기 주소를 devices[].hosts로 내보내고 websync/backup/service.py:471-477이 이를 synced_posts.json에 쓴다. 다중 PC 기기 식별을 위한 의도된 동작이므로 코드 버그로 분류하지 않는다. 개인정보 설명은 실제 공유 필드에 맞춰 수정해야 한다.
- CLAUDE.md의 스케줄러 개별 설명(334행)은 Windows schtasks 전용처럼 쓰였지만, 파일 구조 설명과 후반 로드맵(85, 492-493행) 및 현재 websync/scheduler/manager.py는 launchd/crontab도 지원한다. 현재 구현과 충돌하는 오래된 설명이다.
- 기존 PROJECT_AUDIT.md는 이전 작업트리와 v1.2.2의 결론을 담고 있어 이번 감사 결과로 교체했다. 이전 이슈 중 연결 상태코드 검사, 선택/프리뷰 취소 경계, 크론 관리 블록 보존은 현재 코드에서 수정되어 이번 이슈로 재기재하지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. ISSUE-001: 공유 이력 DB 병합·재export 실패 시 history 게시를 중단하고 실패 결과를 반환한다. 원격 post와 tombstone 보존 회귀 테스트를 릴리스 게이트에 넣는다.

### Phase 2 — Stability

2. ISSUE-002: GUI 설정 저장 결과를 동기화 기동에 연결한다.
3. ISSUE-003: 전체·선택·프리뷰 워커의 예외 및 finally UI 복구를 공통 처리한다.
4. 공유 폴더 push에서 sites/history/manifest의 부분 성공 상태를 명확히 표시하고 재시도 동작을 검증한다.

### Phase 3 — Structural

5. GUI 워커 시작·결과·UI 완료 처리를 한 진입점으로 모아 세 경로가 같은 실패 계약을 사용하게 한다.
6. 공유 파일의 정본 데이터 병합과 SQLite 캐시 갱신을 분리해, DB 쓰기 실패가 정본 게시의 데이터 누락으로 이어지지 않도록 책임을 명확히 한다.
7. 개인정보 문서와 실제 공유 스키마를 맞춘다.

## 8. Test Recommendations

- **Unit:** ISSUE-002에서 _safe_save_config=False일 때 _run_immediate_sync의 스레드 생성이 0회인지 검사한다. ISSUE-003에서 전체·선택·프리뷰 서비스가 각각 예외를 던질 때 완료 콜백 1회, busy 해제, 오류 표시를 검사한다.
- **Integration:** 임시 ConfigManager·SyncHistoryDb·공유 폴더로 로컬/원격의 서로 다른 post와 tombstone을 만든다. ISSUE-001의 import·재export 오류를 각각 주입해 push.ok=False 및 원격 JSON 바이트 불변을 확인한다. 성공 재시도에서는 네 기록의 합집합을 확인한다.
- **End-to-End:** 모의 CrossPoint HTTP 서버에 2xx/5xx/timeout을 주고 수집 → EPUB → 성공 기기만 DB 기록 → 재실행에서 중복 건너뜀을 검사한다. 별도의 GUI 모형에서는 새 기기 주소 저장 실패 시 네트워크 요청이 발생하지 않아야 한다.
- **Concurrency:** 두 프로세스가 같은 파이프라인 락을 요청할 때 하나만 실행되고, 두 공유 폴더 push가 겹쳐도 한쪽의 post/tombstone이 누락되지 않아야 한다. DB import 중 외부 잠금을 걸어 ISSUE-001 실패 동작도 확인한다.
- **Regression:** per_site/daily_digest 및 두 기기에서 한 기기만 업로드 성공하면 성공 기기만 mark_synced_many에 들어가고 실패 기기는 다음 실행에 다시 대상이 되어야 한다. 취소는 다음 사이트/배치 경계에서 새 업로드 없이 끝나야 한다.
- **Platform-specific:** Windows 소스/EXE의 경로·한글 파일명·schtasks, macOS launchd, Linux crontab의 등록/해제와 기존 사용자 작업 보존을 각각 실제 OS에서 검사한다. 파일 다운로드의 중단 시 .part 정리와 원본 보존도 검사한다.

## 9. Final Assessment

| 항목 | 평가 | 근거 |
| --- | --- | --- |
| Functional Correctness | Needs Work | 정상 파이프라인 테스트는 통과하지만 저장 실패 뒤 이전 설정으로 실행된다. |
| Runtime Stability | Needs Work | 워커 예외 시 GUI가 busy에서 복구되지 않는다. |
| Data Integrity | High Risk | 공유 이력 병합 실패에서 정본 기록 누락을 재현했다. |
| Error Resilience | Needs Work | DB 병합 예외를 경고로 낮추고 성공 게시를 계속한다. |
| Cross-platform Robustness | Acceptable | OS별 경로·스케줄러 분기는 있으나 Windows 외 실제 실행은 미검증이다. |
| Test Confidence | Acceptable | 324개 테스트와 스모크가 통과했지만 핵심 실패 분기가 빠져 있다. |

**실제로 먼저 수정할 문제 3개:** (1) 공유 이력 병합 실패 시 게시 중단, (2) GUI 저장 실패 시 동기화 기동 중단, (3) GUI 워커 예외 시 완료·오류 콜백 보장.
