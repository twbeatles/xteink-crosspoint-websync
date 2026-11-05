# Project Audit

> 후속 개선: 2026-11-05 감사의 ISSUE-001~003 및 로컬에서 구현 가능한 안정성·CI·문서 권고를 반영했다. 아래 본문은 감사 당시 기록이다. 원격 receipt와 실제 외부 환경 검증은 완료 구현과 구분하며 [구현 대조표](docs/AUDIT_IMPLEMENTATION.md)에 근거와 남은 범위를 기록한다.

> 감사일: 2026-11-05 (Asia/Seoul) · 기준: `main`, `32eb535`
>
> 기능 구현·런타임 안정성 감사. 애플리케이션·테스트·설정 코드는 수정하지 않았으며 이 보고서만 작성했다. 이전 감사는 Git 이력과 [구현 기록](docs/AUDIT_IMPLEMENTATION.md)에 남아 있다. 이슈 번호는 이번 감사에만 해당한다.

## 1. Executive Summary

**전체 상태: Acceptable. 전체 위험도: Medium.** 핵심 수집·기기별 중복 제거·EPUB·전송 흐름은 잘 구현되어 있다. 설정 검증·revision CAS·원자적 저장, DB 트랜잭션, 프로세스 락, 취소·종료 drain, 업데이트 검증·롤백도 확인했다. 전체 테스트는 **737 passed, 28 skipped**다.

반증 후 남긴 문제는 아래 세 가지다. Critical·High는 확인하지 못했다. §4 제목은 요청된 형식이며 그 안의 이슈가 High 심각도라는 뜻은 아니다.

| 이슈 | 심각도 / 신뢰도 | 영향 |
|---|---|---|
| ISSUE-001: 다운로드 경로 계획 이후의 파일 충돌 | Medium / Confirmed | 덮어쓰기 미승인 상태에서도 다른 작업이 생성한 로컬 파일을 교체함 |
| ISSUE-002: macOS 스케줄 해제 실패의 성공 반환 | Medium / Confirmed | 실패를 알리지 않고 plist·설정 상태를 변경함 |
| ISSUE-003: Linux cron 경로의 `%` 처리 누락 | Medium / Confirmed | 해당 문자가 포함된 경로에서 예약 실행이 실패함 |

**데이터 손상·유실:** DB·설정·공유 JSON의 광범위한 손상 경로는 확인하지 못했다. ISSUE-001은 선택한 다운로드 대상의 로컬 파일 내용이 유실되는 경로로, 임시 파일로 재현했다. 기존 파일에 대한 사전 확인은 구현되어 있으나 확인 이후의 경쟁 조건은 남아 있다.

**가장 먼저 수정할 영역:** 다운로드 완료 시점의 덮어쓰기 정책 강제. 다음은 macOS 해제 결과 검증과 Linux cron 전용 경로 처리다.

## 2. Project Understanding

### 목적·개발 규칙

CrossPoint 펌웨어 기반 Xteink X3/X4용 데스크톱 콘텐츠 수집·EPUB 생성·Wi-Fi 전송 도구다. RSS/Atom, CSS 선택자, 블로그·뉴스레터·YouTube 자막, Calibre/로컬 도서, 기기 파일 관리, Watch, 예약 실행, OPDS, 웹 대시보드, 서명 업데이트를 제공한다.

README, CLAUDE, AGENTS, CONTRIBUTING, 개발자 가이드 일부와 의존성·빌드·CI 설정을 확인했다. main 기본, Spec Kit opt-in 규칙을 따랐다. CLAUDE/AGENTS의 본문 차이는 제목과 AGENTS의 정본 안내뿐이다. 이번에는 커밋·push·릴리즈를 수행하지 않았다.

### 주요 entrypoint와 실행 흐름

| 기능 | 입력 → 검증/핸들러 → 핵심 로직 → 저장/API → 결과 |
|---|---|
| 전체 동기화 | `x3_websync.py:main` → GUI 또는 `--sync` → ConfigManager → `SyncService.run_sync_pipeline` → 공통 락·backup pull → scraper → DB 중복 판정 → 번역/요약 → 기기별 배치 EPUB → `/upload` → 성공 대상 `mark_synced_many` → backup push → bool·상태·알림 |
| 웹 동기화 | 인증된 `/api/sync` → `DashboardHandler.do_POST` → 서비스 수락·락 → 비동기 파이프라인 → 202/409·`/api/status` |
| 선택 전송 | `preview_articles` → source 메타데이터·신규 기사 → GUI 선택 → `sync_selected_articles` → 락·pull·build/upload/mark → 완료 또는 기록한 이력이 있으면 push |
| EPUB 전용 | 선택 → `build_selected_epubs` → 공통 락·최신 설정 → builder → 파일 경로; 전송·완료 이력 기록 없음 |
| 다운로드 | `_download_selected` → 파일명 정리·충돌 안내·경로 계획 → 워커 → `X3DeviceClient.download` → `.part`·fsync·replace → 결과 안내 |
| Watch | 이벤트/복구 큐 → `WatchRetryQueue` → fingerprint·안정성 확인·영속 저장 → 미완료 대상 업로드 → 완료 저장 또는 backoff |
| 예약 실행 | GUI 시간 → `SchedulerManager` → 범위 검사 → schtasks/launchd/crontab → `--sync` |
| OPDS | 인증·경로 → 카탈로그 또는 realpath 범위 검사 → EPUB 스트림 → HTTP 응답 |
| 종료·업데이트 | `_on_close` → 신규 작업 거부·취소 → 서버/Watch 정지·작업 drain·backup flush → 헬퍼 → exe 이동 교체 → smoke → 실패 시 rollback |

### 모듈·상태·저장·외부 의존성

- `pipeline/service.py`: 작업 수락·취소 이벤트, 스레드/프로세스 락, 마지막 결과, backup 훅. 기사 흐름은 `sync_pipeline.py`, `selected_sync.py`, `preview.py`, `epub_only.py`에 분리된다.
- `config/manager.py`, `validator.py`: `config.json`, 구조 검증·결손 키 보강, 프로세스 파일 락, RMW·revision CAS, tmp→replace, `.bak`, 복구 시 rejected 사본.
- `db/history.py`: `sync_history.db`, `(url, device_ip)` 복합 PK, 기기별 이력·삭제 tombstone, commit/rollback·timeout 10초. WAL 설정을 시도한다.
- `upload/device_ids.py`, `upload_results.py`: 안정 기기 ID·alias 조회, 기기별 미전송 기사 배치, 성공 대상만 이력 기록.
- `backup/service.py`: 공유 `sites.json`, `synced_posts.json`, `.websync-replicas/` 병합. 로컬 폴더 락은 여러 PC의 독립적인 클라우드 사본까지 잠그는 전역 락이 아니다.
- `epub/builder.py`, `filenames.py`, `images.py`: 기사 집합 hash가 포함된 파일명, 본문 정화·테마·이미지 내장. `output/`, `logs/`도 실행 데이터다.
- `watch/retry.py`: `calibre_watch.pending_jobs`의 fingerprint/targets/completed, 단일 워커·최대 300초 backoff.
- 필수 의존성: requests, BeautifulSoup/lxml, ebooklib, customtkinter, cryptography, Python tkinter/SQLite. 선택: Pillow, googletrans, youtube-transcript-api, watchdog, Calibre CLI. OS 스케줄 도구와 CrossPoint HTTP API에도 의존한다.
- PyInstaller spec은 선택 기능 패키지를 제외하는 경량 Windows 빌드다. README도 이를 설명한다. 릴리즈 workflow는 테스트 → 빌드 → frozen smoke → 서명 manifest → Release·main manifest 게시 순서다. 이번 감사에서는 실행하지 않았다.

## 3. Audit Coverage & Limitations

### 구조·소스 확인

`.codegraph/` 존재를 확인하고 **실제 CodeGraph MCP `codegraph_explore`를 우선 사용했다.** 다음 소스와 caller/callee·영향 범위를 확인했다.

- `main` → SyncService 전체·비동기 실행·락·종료.
- 전체/선택 동기화 → `group_articles_by_pending_targets` → `upload_to_targets` → `collect_mark_entries` → `mark_synced_many`.
- ConfigManager load/normalize/save/RMW/restore, SQLite 초기화·이관·조회·기록·삭제, backup pull/push의 검증·병합 경계.
- GUI 다운로드 → 경로 계획 → 클라이언트 저장, GUI 예약 등록/해제 → SchedulerManager.
- Watch fingerprint·영속 상태·재시도, Calibre CLI·YouTube 자막 어댑터, 공통 HTTP helper, EPUB builder·이미지·번역, OPDS·대시보드 handler, updater 검증·교체·롤백.

CodeGraph 크기 제한으로 생략된 `sync_pipeline.py` 후반부와 `service.py` 락/실행 본문은 직접 열람으로 보완했다. 문서·설정·테스트 fixture와 관련 테스트도 열람했다. 모든 파일 전수 정독이나 GUI 직접 조작 감사는 아니다. 정적 caller 연결만으로 결함을 확정하지 않고 실제 caller와 보호 장치도 확인했다.

### 실제 실행한 검증

환경: Windows 호스트 / Python **3.15.2**. `tests/conftest.py`의 임시 저장소·자식 프로세스 복사본·storage guard를 확인한 후 실행했다.

```text
python -m pytest -q -p no:cacheprovider --tb=short -ra -W error::RuntimeWarning
737 passed, 28 skipped, 13 warnings in 101.02s
```

27 skip은 `test_preset_epub_pipeline.py:185`의 라이브 네트워크 계약, 1 skip은 `test_storage_isolation.py:121`의 POSIX directory descriptors다. 13 warning은 외부 langsmith의 asyncio DeprecationWarning이다. 시작 시 pytest-asyncio fixture loop scope 설정 경고도 표시됐다. 테스트 실패로 집계되지 않았다.

전체 실행에는 기존 pipeline HTTP integration·다중 프로세스 락·백업/DB/설정·종료 수명주기·업데이트 rollback·다운로드 충돌 테스트가 포함된다. 통과가 아래 신규 조건까지 보장하지는 않는다.

추가 일회성 Python 재현은 저장소 밖 임시 디렉터리에서 실행했다. import 전 `X3_WEBSYNC_STORAGE_ROOT`를 지정했고 실제 기기에 접속하지 않았다.

| 재현 | 입력/주입 | 결과 |
|---|---|---|
| R1 | overwrite=False로 경로 계획; fake HTTP 스트림 도중 같은 경로에 경쟁 파일 생성 | `planned_conflict=false`, True 반환, 최종 내용 `DEVICE-CONTENT`; 경쟁 파일 교체 |
| R2 | darwin 분기, unload exit 5·오류 stderr를 mock | True 반환, 빈 last_error, plist 삭제 호출 |
| R3 | `/home/reader/100%news/...`, `/usr/bin/python3`, POSIX join으로 실제 명령 생성 함수 호출 | cd/script/log 경로에 보호되지 않은 `%` 출력 |

첫 재현은 결과 출력 후 열린 임시 로그 핸들러 때문에 폴더 정리에서 실패했다. `logging.shutdown()`을 추가한 재실행은 동일 결과로 exit 0 종료했다. 감사 스크립트의 정리 문제이며 앱 결함으로 분류하지 않았다.

### 한계·미확인 환경

- 실제 X3/X4: 한글 이름 표시, 동일 원격 경로 덮어쓰기, 응답과 영속 저장의 일치, 전원 단절 복구.
- 실제 macOS launchd·Linux cron 데몬. 해당 분기는 mock/명령 생성·코드로 확인했다. cron의 `%` 해석은 [Cronie 원본 crontab(5)](https://github.com/cronie-crond/cronie/blob/master/man/crontab.5)로 교차 확인했다.
- 실제 클라우드 클라이언트, 라이브 사이트 27건, AI/번역/YouTube/Calibre 실서비스.
- 현재 원격 CI 결과, 서명키 운영, 신규 frozen 빌드/실행. workflow 열람을 배포 검증으로 대체하지 않았다.
- dependency 설치, 앱 GUI 실행, 실제 예약 등록/해제, 사용자 config/DB/도서 변경은 하지 않았다. 타입 검사·coverage 측정도 실행하지 않았다.

## 4. High-Risk Issues

### [ISSUE-001] 다운로드 검사 이후 생성된 로컬 파일을 승인 없이 덮어씀

- **위치:** `websync/gui/device_files/actions.py:227` `_download_selected`; `websync/upload/local_path.py:29` `plan_local_downloads`; `websync/upload/device_client.py:261` `download` (교체: 305행).
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** GUI는 작업 전 존재 여부로 이름을 정하지만 저장 API에는 overwrite 정책을 전달하지 않는다. 완료 시 `os.replace(temp_path, local_path)`는 그 사이 생긴 파일도 교체한다.
- **발생 조건:** 계획 당시 대상 이름이 비어 있거나 새 번호 이름이 선택되었지만 워커 시작·다운로드·앞선 배치 처리 동안 다른 앱/클라우드 클라이언트가 같은 파일을 만든다. 덮어쓰기를 선택하지 않은 경우에도 적용된다.
- **영향:** 해당 로컬 파일 내용 유실. 선택한 경로 밖 탈출이나 DB 파괴는 아니다. 단독 다운로드에서는 발생하지 않으므로 Medium으로 한정한다.
- **근거:** R1에서 conflict=False·overwrite 미승인 상태로 스트림 중 `CONCURRENT-LOCAL-FILE`을 생성했다. True 반환 후 내용은 `DEVICE-CONTENT`였다.
- **반증 확인:** 기존 충돌 안내·기본 새 이름 저장·배치 내 casefold 중복 방지·basename 정리·UUID `.part`의 xb/fsync를 확인했다. 이들은 계획과 임시 파일을 보호하지만 최종 경로의 배타적 게시를 보장하지 않는다. GUI busy는 외부 writer를 잠그지 않는다. GUI도 같은 download API를 그대로 호출한다.
- **호출/영향 범위:** CodeGraph 확인: `_download_selected` → `plan_local_downloads` → worker → `X3DeviceClient.download` → replace. 기기→PC 다운로드에 한정된다.
- **권장 수정 방향:** overwrite 정책을 저장 계층까지 전달한다. 미승인 모드의 최종 게시에는 기존 대상을 교체하지 않는 배타적 연산을 사용하고 충돌 시 새 이름 또는 명확한 실패를 반환한다. 직전 exists 재검사만 추가하면 race가 남는다. 승인 모드만 replace를 허용한다.
- **필요한 회귀 테스트:** 계획 후·스트림 중·최종 게시 직전에 각각 파일을 생성한다. 미승인 모드는 경쟁 바이트 보존과 새 이름/충돌 오류를, 승인 모드만 교체를 기대한다.

### [ISSUE-002] macOS 스케줄 해제 실패를 성공으로 처리하고 plist를 삭제함

- **위치:** `websync/scheduler/manager.py:336–345` `unregister_task`; `websync/gui/sync_tab/schedule.py:35` `_unregister_schedule`.
- **우선순위:** Medium
- **신뢰도:** Confirmed (실패 무시·성공 반환·삭제 호출을 mock 재현; 실제 launchd 잔존 실행은 미재현)
- **문제:** darwin 분기는 unload의 returncode를 확인하지 않는다. 비정상 종료해도 plist를 삭제하고 True를 반환하며 `_fail`을 호출하지 않는다.
- **발생 조건:** unload가 프로세스 생성 예외 대신 nonzero로 실패한다. 이미 로드된 job을 내리지 못하는 권한·launchd 상태/도메인 문제 등이 해당한다.
- **영향:** GUI는 성공 안내 후 schedule.enabled=False를 저장한다. 실제 job이 남았다면 자동 전송이 계속될 수 있다. plist 삭제 후 파일 존재 기반 상태 조회도 미등록으로 보일 수 있다. job 잔존 여부는 실패 원인에 따라 다르다.
- **근거:** R2에서 exit 5·stderr 오류에도 True, last_error 빈 문자열, plist 삭제 호출을 확인했다. GUI는 True만으로 성공 분기에 진입한다.
- **반증 확인:** `_fail`·GUI 오류 표시는 존재하고 Windows/Linux 해제는 종료 코드를 확인한다. macOS 해제는 이를 우회한다. except는 예외만 처리하므로 반환된 실패 코드를 막지 못한다. 이미 미등록인 상태와 실제 unload 실패를 구분하는 후속 조회도 없다.
- **호출/영향 범위:** CodeGraph 확인: GUI `_unregister_schedule` → `SchedulerManager.unregister_task` → launchctl unload → plist 삭제 → GUI 설정 저장·get_task_status.
- **권장 수정 방향:** 결과를 판정하고 실패는 `_fail`로 전달한다. 실패 시 plist·enabled 상태를 보존한다. 이미 job이 없는 상태를 멱등 성공으로 취급하려면 명시적인 조회로 구분한다. 상태 표시에 로드된 job 확인도 검토한다.
- **필요한 회귀 테스트:** 활성 job의 unload exit 5는 False·오류 내용·plist 보존·성공 안내 미발생을 기대한다. exit 0과 이미 미등록인 경우도 별도 검증한다.

### [ISSUE-003] Linux 예약 경로의 `%`가 cron 구문으로 해석됨

- **위치:** `websync/scheduler/manager.py:212–223` `_build_cron_line`; `_register_linux:273`.
- **우선순위:** Medium
- **신뢰도:** Confirmed (생성 문자열과 cron 규칙으로 확인; 실제 Linux 데몬 E2E 미실행)
- **문제:** 경로에 shlex.quote만 적용한다. cron은 shell 실행 전에 보호되지 않은 `%`에서 명령을 나누고 뒤를 표준입력으로 처리하므로 shell 인용만으로는 보호되지 않는다. [Cronie 원본 매뉴얼](https://github.com/cronie-crond/cronie/blob/master/man/crontab.5)
- **발생 조건:** 프로젝트·스크립트·Python 경로에 `%`가 포함된다. 예: `/home/reader/100%news/x3_websync.py`.
- **영향:** 등록은 성공해도 예약 시 잘린 명령이 실행되어 sync에 도달하지 못한다. 정상 경로 이동으로 우회 가능하며 일반 경로에는 영향이 없다.
- **근거:** R3은 `30 7 * * * cd /home/reader/100%news && /usr/bin/python3 /home/reader/100%news/x3_websync.py --sync >> /home/reader/100%news/logs/cron.log 2>&1`을 생성했다. 세 경로 모두 `%`가 보호되지 않는다.
- **반증 확인:** 시간 검증·shell quoting·기존 crontab 보존·읽기 실패 시 쓰기 중단은 존재한다. cron 전처리는 보호하지 않는다. 상위 GUI도 해당 경로를 거부하지 않고 등록 함수는 문자열을 그대로 설치한다. 기존 테스트는 공백 인용·마커 보존을 검사하지만 cron 해석을 검증하지 않는다.
- **호출/영향 범위:** CodeGraph 확인: GUI `_register_schedule` → register_daily_task → _register_linux → _build_cron_line → crontab 설치 → 예약 실행 실패. Linux 예약에 한정된다.
- **권장 수정 방향:** shell 인용과 cron 명령 필드 escaping을 별도로 적용하거나 안전한 고정 경로 launcher를 사용한다. Python·프로젝트·로그 경로를 모두 처리하고 줄바꿈 포함 경로도 거부/처리한다.
- **필요한 회귀 테스트:** `%`·공백·여러 `%` 조합에서 cron 전처리 후 원래 argv가 유지되는지 검사한다. 격리된 Linux 환경에서 동일 명령 해석을 검증한다.

## 5. Potential Functional Gaps

| 구분 | 보완점 | 현재 한계 |
|---|---|---|
| Confirmed Gap | 원격 receipt·재조정 | 기기 저장 후 응답 유실/로컬 기록 전 종료는 재전송을 유발할 수 있다. Watch도 이를 명시한다. exactly-once는 현재 계약이 아니므로 새 버그로 계산하지 않는다 |
| Confirmed Gap | 현재 CI의 macOS 런타임 | test.yml은 Linux 전체/Python 3.15와 Windows 일부/Python 3.10이다. 실제 macOS 예약을 확인하지 않는다 |
| Likely Gap | 전체 deadline·취소 지연 상한 | 개별 HTTP timeout·retry·크기 제한은 있지만 전체 경과시간 상한은 별도다. 번역은 텍스트 조각마다 요청하고 종료 drain은 완료를 기다린다. 느린 네트워크 종료 지연 가능성이 있으나 무한 hang은 재현하지 않았다 |
| 추정 | 장기 보존·자원 기준 | Watch `_finished`, 출력 EPUB·replica/tombstone에 장기 부하 기준이 있으면 좋다. 실제 자원 고갈 증거는 없다 |

이미 구현된 이미지 내장·YouTube 신구 API 호환·EPUB-only·선택 전송·부분 성공 이력·replica·취소·업데이트 rollback을 미구현으로 분류하지 않았다. 경량 EXE의 optional 제외도 문서화된 정책이다.

## 6. Documentation Mismatches

1. CLAUDE/AGENTS의 2026-11-02 후속 요약은 예약 등록·해제 실패가 `_fail` → last_error → GUI로 전달된다고 설명한다. macOS 해제의 nonzero 종료는 이 경로를 거치지 않는다(ISSUE-002).
2. 같은 요약의 다운로드 사전 충돌 확인·기본 새 이름 저장은 구현되어 있다. 계획 후 생성된 파일까지 보호하는 보장은 아니므로 절대적인 무덮어쓰기 보장으로 확대해서는 안 된다(ISSUE-001).
3. README의 “Zero Duplicate Delivery”는 개요 표현이며 후반 Reliability 절은 단일 PC 자동 전송·cross-PC 락 한계를 명시한다. 전체 문맥상 새 문서 오류로 계산하지 않았지만 요약에도 조건을 붙이면 좋다.

그 밖에 확인한 핵심 기능·경량 빌드 설명의 새로운 중대한 불일치는 찾지 못했다. 역사적 로드맵은 완료 안내가 있으므로 현재 미구현 주장으로 읽지 않았다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

- **ISSUE-001:** 최종 파일 게시에 overwrite 정책을 반영하고 경쟁 파일 보존 테스트를 먼저 추가한다. 제한적이나 데이터 유실 가능성이 있으므로 우선한다.
- 추가 Critical/High 이슈는 없다. 실사용자 데이터로 재현할 필요도 없다.

### Phase 2 — Stability

- **ISSUE-002:** unload 결과·실제 상태를 판정하고 실패 시 plist/config를 유지한다.
- **ISSUE-003:** cron 전용 escaping·제어문자 정책과 최종 해석 결과 검증을 추가한다.
- macOS CI·optional 계약 범위를 명확히 하고 느린 응답·취소·종료 시간 기준을 마련한다.

### Phase 3 — Structural

- 다운로드 경로 선정·게시를 명시적인 저장 정책으로 묶어 호출자가 미승인 overwrite를 빠뜨리지 못하게 한다.
- OS 예약 작업 결과와 설정 저장 결과를 구분하는 상태 계약을 둔다.
- 원격 receipt는 기기 지원·재시도 정책을 정한 별도 설계로 진행한다. 클라우드 로컬 락으로 전역 exactly-once를 약속하지 않는다.

실제 코드는 수정하지 않았다.

## 8. Test Recommendations

| 종류 | 입력·장애 조건 | 기대 결과 |
|---|---|---|
| Unit / Regression: ISSUE-001 | overwrite=False 계획 뒤·스트림 중 파일 생성 | 경쟁 바이트 보존; 새 이름 또는 충돌 오류. 승인 모드만 교체 |
| Concurrency: ISSUE-001 | barrier로 최종 게시 직전 외부 프로세스가 같은 경로 생성 | no-overwrite 계약 유지·부분 파일 정리 |
| Unit / GUI: ISSUE-002 | unload exit 5·stderr, 활성 job 가정 | False·last_error·plist 보존; 성공 안내·enabled=False 저장 없음 |
| Platform-specific: macOS | 임시 label 등록·시간 변경·해제·실패 주입 | launchd 실제 상태·plist·UI 일치; 사용자 job 불변 |
| Unit / Regression: ISSUE-003 | `%`, 공백, 작은따옴표, 백슬래시 조합 | cron 전처리 후 원래 argv·로그 경로 유지; 줄바꿈 정책 검증 |
| Platform-specific: Linux | 임시 launcher·fake sync target으로 명령 해석 | fake target 정확히 1회·원래 cwd/argv; 사용자 crontab 미변경 |
| End-to-End: 전체/선택/합본 | A에 글1, B에 글2 이력; 두 글 수집; B 전송 실패 후 재시도 | 각 기기에 미전송 글만 포함·성공 대상만 기록·미완료만 재시도 |
| Integration: 공유 폴더 | 잘린/구조 오류 JSON·동시 writer·push 실패 | pull 실패는 전송 전 중단·원본 보존·실패 노출·정상 재시도 합집합 |
| Concurrency: 종료 | 업로드/DB commit/Watch backoff 중 close | 신규 작업 거부·이력/pending 보존·drain 후 종료·지연 관찰 가능 |
| Integration: 복구 | 구조 오류 원본·정상 전체 백업·오래된 revision writer | 실패 시 bytes/revision/bak 불변·성공 시 rejected 보존·동시 writer 정책 검증 |
| End-to-End: HTTP | 잘못된 토큰·과대 body·탈출 경로·동시 sync 요청 | 인증/400/403/409, 외부 파일 미노출, 단일 작업·상태 조회 |
| Regression: 업데이트 | staged hash/size 불일치·이동 사이 실패·smoke 실패 | 기존 exe 보존/복구·사용자 데이터 불변·다음 시작 실패 결과 표시 |
| External contract | 기기 저장 뒤 응답 유실·앱 재시작 | 현재 재전송 불확실성 표시; receipt 도입 시 조정 기대값 별도 정의 |

기존 테스트와 겹치는 행은 무조건 증설하라는 뜻이 아니다. 이번 세 누락 조건과 실제 플랫폼 경계를 우선 보강한다.

## 9. Final Assessment

| 영역 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 핵심 흐름·전체 테스트 정상. 플랫폼 예약 조건 수정 필요 |
| Runtime Stability | Acceptable | 공통 락·취소·drain·오류 결과 존재. 느린 외부 호출·실플랫폼 장기 실행 미검증 |
| Data Integrity | Needs Work | DB·설정 보호는 양호하지만 다운로드의 제한적 파일 유실 재현 |
| Error Resilience | Acceptable | 사이트/backup/부분 전송·rollback 처리. macOS false success 잔존 |
| Cross-platform Robustness | Needs Work | Windows 전체 suite 통과. macOS 해제·Linux cron 결함과 실환경 검증 공백 |
| Test Confidence | Acceptable | 737 통과. 28 skip·실기기/서비스·frozen·실 OS 예약은 별도 검증 필요 |

**실제로 먼저 수정할 문제 3개:**

1. **ISSUE-001:** 다운로드 완료 시 미승인 로컬 파일 교체를 막는다.
2. **ISSUE-002:** macOS 스케줄 해제 실패를 전파하고 plist·설정을 보존한다.
3. **ISSUE-003:** Linux cron의 `%` 포함 경로 해석을 바로잡는다.
