# Project Audit

> 후속 개선: 2026-11-21 감사에서 ISSUE-001~006 및 안정성 보완점을 도출했다. 이전 감사(2026-11-05) 기록은 [구현 기록](docs/AUDIT_IMPLEMENTATION.md)에 남아 있다.
>
> 감사일: 2026-11-21 (Asia/Seoul) · 기준: `main`, `faf9f26` (clean, `git status` 무변경)
>
> 기능 구현·런타임 안정성 관점의 one-shot 감사. 애플리케이션·테스트·설정 코드는 수정하지 않았으며 이 보고서만 작성한다. 기존 `PROJECT_AUDIT.md`(2026-11-05 기록)는 이번 감사로 대체된다. 이전 감사·구현 대조는 [구현 기록](docs/AUDIT_IMPLEMENTATION.md)에 남아 있다.

## 1. Executive Summary

**전체 상태: Acceptable. 전체 위험도: Low-Medium.**

핵심 흐름(수집 → 기기별 중복 제거 → EPUB 빌드 → Wi-Fi 전송 → 성공분만 이력 기록 → 공유 폴더 push)은 견고하다. 설정 revision CAS·원자 저장·`.bak`·rejected 보존, DB 복합 PK·트랜잭션, 스레드+프로세스 파이프라인 락, 배치 경계 취소, 종료 drain, Windows 스케줄러 261자 방어·OEM 디코딩, crontab 읽기 실패 시 비파괴, macOS unload 검증, OPDS·대시보드 인증·경로 차단, 업데이터 move-swap·smoke·rollback도 코드로 확인했다.

반증(상위 caller 검증·예외 처리·락·제약·도달 가능성·dead code 여부)을 거친 뒤 남긴 문제는 아래 6건이다. **Confirmed High/Critical 데이터 파괴 결함은 확인하지 못했다.**

| # | 이슈 | 심각도 / 신뢰도 | 한 줄 영향 |
|---|---|---|---|
| ISSUE-001 | 업로드 단일 시도·재시도 없음 + 전송 중 취소 불가 | Medium / Confirmed | 일시적 네트워크 흔들림에 부분 실패, 대용량 전송 중 취소가 다음 배치까지 지연 |
| ISSUE-002 | `local_import` 폴백 저장의 무조건 덮어쓰기 | Medium / Confirmed(코드 사실)·발동은 Likely | 동시 쓰기 경합 시 최신 설정이 옛 스냅샷으로 회귀 가능 |
| ISSUE-003 | 공유 JSON 고정 `.tmp` 충돌 | Medium / Confirmed(코드 사실)·발동은 Likely-low | 다중 프로세스 동시 쓰기 시 tmp 경합 가능 (폴더 락이 1차 방어) |
| ISSUE-004 | NaverCafe 본문 중첩 `<body>`로 잘못된 XHTML | Medium / Confirmed | 특정 카페 글에서 챕터 XHTML 무결성 훼손, 리더별 본문 누락 가능 |
| ISSUE-005 | 요약 단계 취소 미배선 (번역만 배선) | Medium / Confirmed | AI 요약 HTTP(20~30s) 중 취소가 기사 경계까지 지연 |
| ISSUE-006 | 응답 유실 시 재전송 (receipt 없음, 설계상 한계) | Medium / Likely(근거 강함) | 기기 저장 후 응답 유실 시 다음 실행에 중복 전송 가능 |

**데이터 손상/유실 가능성:** DB·설정·공유 JSON의 광범위한 손상 경로는 확인하지 못했다. `publish_local_download` 배타 게시, DB PK·트랜잭션, 설정 원자 저장·`.bak`·`.corrupt` 격리는 확인했다. 남은 쓰기 경합(ISSUE-002/003)은 좁은 경쟁창이며, ISSUE-006은 중복 전송(가용성)이지 기존 데이터 파괴가 아니다.

**가장 먼저 수정해야 할 영역:** (1) 업로드 재시도·취소 전파(ISSUE-001, 체감 실패율과 직접 연결), (2) `local_import` 폴백 CAS 준수(ISSUE-002, 설정 회귀 방지), (3) NaverCafe `<body>` 정규화(ISSUE-004, EPUB 무결성).

## 2. Project Understanding

### 목적

CrossPoint 펌웨어 기반 Xteink X3/X4용 데스크톱 콘텐츠 파이프라인이다. RSS/Atom·CSS 선택자·Velog·Naver 블로그/카페·Tistory·Brunch·Newneek·YouTube 자막·Substack·뉴스레터를 수집해 e-ink 최적화 EPUB으로 빌드하고 Wi-Fi로 전송한다. SQLite 기기별 이력으로 증분 동기화하고, Calibre 서재·로컬 파일·기기 파일 관리·Watch·예약 실행·OPDS·웹 대시보드·Ed25519 서명 업데이트를 제공한다.

### 주요 entrypoint

`x3_websync.py:main` → 분기: `--smoke`(모듈·카탈로그 검증) / `--apply-update`(헬퍼) / `--recover-config`(검증 후 복원, 전송 없음) / `--sync`(백그라운드 파이프라인) / GUI(`SyncAppGui`). GUI만 instance lock을 사용하고, CLI/GUI 직렬화는 `SyncService`의 스레드+프로세스 파이프라인 락에 위임한다.

### 핵심 모듈

- `websync/pipeline/service.py`: 작업 수락·취소 이벤트·스레드/프로세스 락·마지막 결과·backup 훅. 기사 흐름은 `sync_pipeline.py`(전체), `selected_sync.py`(선택), `preview.py`(미리보기), `epub_only.py`(EPUB 전용)에 분리.
- `websync/config/manager.py` + `validator.py`: `config.json`, 구조 검증·결손 키 보강, 프로세스 파일 락, RMW·revision CAS(`save_config(expected_revision)`/`update_config`), pid·thread·uuid tmp→fsync→replace, `.bak`, 복구 시 `.rejected.<uuid>.json` 보존.
- `websync/db/history.py`: `sync_history.db`, `(url, device_ip)` 복합 PK, 기기별 이력·`deleted_posts` tombstone, `_connect` commit/rollback/close + `timeout=10.0`, WAL 시도 후 폴백.
- `websync/upload/uploader.py` + `device_ids.py`: 안정 기기 ID·alias 조회, 배치 전송(`ThreadPoolExecutor`, 최대 4), `only_ips` 부분 재시도, 결과 키는 IP/호스트.
- `websync/backup/service.py` + `atomic_io.py` + `format.py` + `local_import.py`: 공유 `sites.json`·`synced_posts.json`·replica 병합, 폴더 락(비차단·busy 스킵), pull 실패 시 전송 중단·push 스킵.
- `websync/epub/builder.py` + `sanitize.py` + `filenames.py` + `images.py`: 기사 집합 hash 파일명, 본문 정화·이미지 내장(PNG/JPEG/GIF, 4MB/장·24MB/권·32장·30s 예산).
- `websync/watch/retry.py` + `watch/calibre.py`: 단일 워커·경로별 due·지수 backoff(2.0, 최대 300s), fingerprint·안정성 재확인, durable 저장 후 완료 제거.
- `websync/scheduler/manager.py`: schtasks/launchd/crontab, `WINDOWS_TR_MAX_LENGTH=261` 사전 거부, OEM 코드페이지 디코딩, cron 실패 읽기 시 비파괴.
- `websync/servers/opds.py` + `servers/dashboard/`: 토큰 인증·HMAC 세션 쿠키·POST 64KB 제한·경로 차단(basename+realpath+normcase).
- `websync/integrations/notifier.py`·`calibre.py`: 플랫폼별 토스트·`calibredb` argv 실행(로컬 설정 신뢰 경계).

### 데이터 저장 방식

`config.json`(revision CAS·원자 저장·`.bak`·`.corrupt`/`.rejected` 격리), `sync_history.db`(복합 PK·삭제 tombstone·LWW 병합), 공유 폴더 JSON(검증-선행-쓰기·tombstone LWW), `output/` EPUB, `logs/` 날짜별 로그.

### 외부 의존성

필수: `requests`, `beautifulsoup4`/`lxml`, `ebooklib`, `customtkinter`, `cryptography`, 표준 `tkinter`/`sqlite3`. 선택: `Pillow`, `googletrans>=4.0.2,<5`, `youtube-transcript-api`, `watchdog`, Calibre CLI. OS 스케줄 도구·CrossPoint HTTP API·Ollama/OpenAI·LibreTranslate에도 의존한다.

### 핵심 실행 흐름

`Entry(x3_websync.py) → Handler(SyncService 락 수락) → Core(backup pull → Scraper → needs_sync/pending → 번역/요약 → 기기별 배치 EPUB) → DB/File/API(mark_synced_many / output/*.epub / http://{ip}/upload) → Result(bool·상태·토스트·backup push)`.

## 3. Audit Coverage & Limitations

### 실제 확인한 주요 모듈 (직접 열람)

- 진입·락·취소: `x3_websync.py`, `websync/pipeline/service.py`(`_try_acquire`/`_release`/`run_sync_pipeline`/`_run_pipeline_body`), `websync/pipeline/sync_pipeline.py`(1~170행대 취소·레거시 이관·배치 경계), `websync/core/process_lock.py`·`instance_lock.py` 개념 대조.
- 설정·DB·백업: `websync/config/manager.py`(404~480행 CAS·원자 저장), `websync/db/history.py`(42~116행 connect·WAL·마이그레이션, 239~361행 mark·get_history), `websync/backup/atomic_io.py`(15~33행 고정 tmp), `websync/backup/local_import.py`(145~174행 폴백 저장).
- 전송·EPUB: `websync/upload/uploader.py`(42~140행 파일명·timeout·단일 POST, 175~226행 병렬 전송), `websync/epub/builder.py`(124~155행·234~266행 chapter 조립), `websync/epub/sanitize.py`(29~58행), `websync/pipeline/summarizer.py`(40~57행 escape·fail-open), `websync/pipeline/translator.py`(15~34행 예산·취소).
- 스크래퍼: `websync/scrapers/naver_cafe.py`(150~206행 API·폴백·`str(container)` 반환).
- 서버·스케줄러·알림: `websync/servers/dashboard/handler.py`(26~28행·83~249행 라우팅), `websync/scheduler/manager.py`(40·113·212·322·352행대), `websync/integrations/notifier.py`(46~57행 macOS).
- 문서·설정: `README.md`, `CLAUDE.md`·`AGENTS.md` 본문 대조, `pyrightconfig.json`(전면 `none`), `pytest.ini`, `websync/__init__.py` 버전.

### CodeGraph 분석 호출 관계

- CodeGraph MCP `codegraph_explore`를 본 세션에서 직접 1회 사용했다. 쿼리: `run_sync_pipeline SyncService upload_to_targets mark_synced pipeline locks cancellation`.
- 확인된 blast radius: `mark_synced` 28 caller·DB 테스트군, `SyncService` 55 caller(GUI·portable wizard·파이프라인), `run_sync_pipeline_locked` 2 caller(service 경유), `upload_to_targets` 10 caller(파이프라인·Calibre 탭·Watch), `run_sync_pipeline` 37 caller(`x3_websync.py`·GUI sync_control).
- 워크플로 백그라운드 자식들의 구조 탐색 결과(락·CAS·트랜잭션·서버·업데이터)는 위 직접 열람으로 교차 검증한 것만 최종 근거로 사용했다. 자식 주장 중 `summary_html` 미정화·`device_client` finally 등은 직접 열람으로 반증/완화했다.

### 실행한 테스트 (본 세션 직접 실행)

- `python -m pytest tests/test_uploader.py tests/test_epub_filenames.py tests/test_epub_sanitize.py -q` → **24 passed**.
- `python -m pytest tests/test_config_validator.py tests/test_db.py tests/test_backup_atomic_io.py -q` → **36 passed**.
- 합계 **60 passed**. 전체 스위트·frozen 빌드·실기기는 실행하지 않았다.

### 확인하지 못한 환경/외부 서비스

실 X3/X4 기기(한글 표시·원격 덮어쓰기 의미·응답/영속 일치), 실 macOS launchd·Linux cron 데몬 E2E, 실 클라우드 폴더 동기화 지연, 라이브 피드·AI/번역·YouTube·Calibre 실서비스, 원격 CI 매트릭스·서명키·신규 frozen 빌드, GUI 직접 조작. `replicas.py` 내부 LWW·`selector_assistant` 분석·점수 모듈·번역 30초 예산의 코드 직접 열람도 범위 밖으로 남겼다.

### 분석 한계

- CodeGraph 1회 + grep·직접 열람 중심이므로 전수 호출 그래프가 아니다.
- 동시성·타이밍 이슈는 코드·락·테스트로 추론했으며 실환경 재현은 하지 않았다.
- `Likely`는 코드 근거가 강하나 런타임 재현까지 못한 항목에만 부여했고, `Speculative`는 High-Risk에 넣지 않았다.
- 기존 `docs/AUDIT_IMPLEMENTATION.md`의 "전체 700+ passed·basedpyright clean"은 기록 인용이며 본 세션 실행 결과로 주장하지 않는다.

## 4. High-Risk Issues

### [ISSUE-001] 업로드 단일 시도·재시도 없음 + 전송 중 취소 불가

- **위치:** `websync/upload/uploader.py:80-140, 175-226`(`_calc_timeout`·`_upload_to_ip`·`upload_to_targets`), `websync/pipeline/sync_pipeline.py:134-140, 240-259` 배치 경계 취소
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** `_upload_to_ip`는 `requests.post(..., timeout=25+5s/MB)` 단일 블로킹 호출이며 cancel 파라미터·취소 체크·재시도 루프가 없다. `Timeout`·예외는 `False`+`last_errors` 기록 후 반환하고 호출당 POST 1회로 끝난다. `upload_to_targets`는 `ThreadPoolExecutor`+`as_completed` 블로킹 대기이며 취소 전달이 없다. 파이프라인 취소 검사는 사이트·배치 경계에서만 수행되므로 진행 중 POST는 timeout까지 대기한다.
- **발생 조건:** 일시적 Wi-Fi 흔들림·기기 절전·대용량 EPUB(수십 MB) 전송 중 사용자가 취소를 누른 경우.
- **영향:** 일시 오류가 곧바로 부분 실패가 되어 다음 실행까지 미뤄진다. 취소 체감이 나쁘다(대용량 1건이면 수십 초~수 분 대기). 데이터 파괴는 아니다. 성공 IP만 `mark_synced_many`하므로 중복 기록은 없다.
- **근거:** `uploader.py:113-140` 직접 열람(단일 POST·재시도 없음), `uploader.py:204-226` 직접 열람(병렬 제출 후 결과 수집만), `sync_pipeline.py:134-140` 직접 열람(배치 경계 취소). 본 세션 실행 `test_uploader.py` 24 passed 중 재시도 계약이 없음을 확인.
- **반증 확인:** 부분 성공만 이력 기록·`only_ips` 부분 재시도·`mark` 전 `is_synced` 재확인은 확인했다. 그러나 이들은 실패 후 복구가 아니라 다음 실행으로 미루는 구조라 단일 시도 문제를 해소하지 못한다. 스레드·프로세스 락·`shutdown_pipeline` 협력 취소는 전송 스레드 자체를 강제 중단하지 못한다.
- **호출/영향 범위:** CodeGraph 기준 `upload_to_targets` 10 caller(전체·선택 파이프라인·Calibre 탭·Watch), `run_sync_pipeline` 37 caller. 영향 모듈: 전체·선택·합본 파이프라인, Calibre 직접 전송, Watch 업로드.
- **권장 수정 방향:** 일시 오류(Timeout·ConnectionError·5xx)에 한해 1~2회 제한 재시도 + 지수 백오프를 `uploader` 내부에 추가한다. 취소는 `threading.Event`를 `upload_to_targets`까지 전파하되 진행 중 POST 강제 종료는 하지 않고 다음 IP·다음 배치에서 중단하는 협력 취소를 문서화한다. 타임아웃 상한도 함께 명시한다.
- **필요한 회귀 테스트:** 일시적 `ConnectionError` 1회 주입 후 동일 파일 전송 → 2번째 시도에서 성공하고 이력 1건. 대용량 흉내(작은 timeout 주입) 전송 중 취소 → 다음 배치 경계에서 `cancelled`로 끝나고 진행 중 스레드는 timeout 내 정리.

### [ISSUE-002] `local_import` 폴백 저장의 무조건 덮어쓰기

- **위치:** `websync/backup/local_import.py:168-173`, 대비 `websync/config/manager.py:404-429`
- **우선순위:** Medium
- **신뢰도:** Confirmed(코드 사실), 발동 조건은 Likely
- **문제:** 사이드카 병합 저장은 1차로 `config_manager.update_config(_apply)`(RMW·CAS)를 시도하지만, 예외 시 폴백으로 `config["sites"]=merged; save_config(config)`(revision 검사 없음)를 호출한다. `_apply` 내부에서 디스크 최신과 재병합하므로 1차 경로는 안전하나, 폴백 경로는 병합 전 스냅샷을 그대로 덮어쓴다.
- **발생 조건:** 폴백이 발동하는 예외(`update_config` 중 충돌·IO 오류)와 동시에 다른 writer(GUI 편집·백업 pull·다른 프로세스)가 설정을 바꾼 경우.
- **영향:** 동시 변경분이 옛 스냅샷으로 회귀한다(사이트 추가·토큰·기기 ID 유실 가능). `.bak`은 남으므로 완전 손실은 아니나 자동 복구는 아니다.
- **근거:** `local_import.py:152-173` 직접 열람(폴백에 `expected_revision` 없음), `manager.py:404-429` 직접 열람(정상 경로는 CAS·RMW). `test_backup_atomic_io.py` 통과는 원자 replace만 보장하고 CAS 우회는 다루지 않는다.
- **반증 확인:** 정상 경로 RMW·`read_json_safe`·tombstone LWW·pull 실패 시 push 스킵은 확인했다. 그러나 폴백 분기는 그 보호를 우회하므로 반증되지 않는다. 도달 가능성은 낮으나(예외+동시 쓰기 결합) GUI·백업·Watch가 모두 writer인 구조에서 현실적이다. dead code가 아니다.
- **호출/영향 범위:** 시작 시 자동 이어받기·수동 가져오기 → `ConfigManager` → `config.json`. 영향: 사이트 목록·삭제 tombstone·기기·토큰.
- **권장 수정 방향:** 폴백을 삭제하거나, 폴백에서도 디스크 revision을 다시 읽어 `_apply`를 재실행한 뒤 `save_config(expected_revision=disk_rev)`로 저장한다. 실패하면 저장하지 말고 `sites_changed=False`+경고로 반환한다.
- **필요한 회귀 테스트:** `update_config` 1회 실패 주입 + 병행 writer가 revision을 올린 상태 → 폴백 후에도 병행 writer 변경이 보존되고 병합분만 추가됨. 폴백 2회 연속 실패 → 파일 미변경·에러 반환.

### [ISSUE-003] 공유 JSON 고정 `.tmp` 충돌

- **위치:** `websync/backup/atomic_io.py:15-33`, 대비 `websync/config/manager.py:446-449`(pid·thread·uuid tmp)
- **우선순위:** Medium
- **신뢰도:** Confirmed(코드 사실), 발동 확률은 Likely-low
- **문제:** `write_json_atomic`의 tmp 경로가 `{path}.tmp` 고정이라 같은 공유 파일을 두 프로세스가 동시에 쓰면 tmp를 밟는다. `os.replace` 자체는 원자적이나 tmp 경합 시 한쪽 내용이 잘리거나 섞일 수 있다.
- **발생 조건:** 두 PC·두 프로세스가 같은 클라우드 사본에 거의 동시에 push하거나, 폴더 락이 없거나 우회된 경로로 쓸 때.
- **영향:** 공유 `sites.json`·`synced_posts.json` 일시 손상 가능. `read_json_checked`가 손상본을 `JsonReadError`로 거부하고 원본 보존 루틴이 있어 영구 손실 가능성은 낮으나 push 실패·재시도 부담이 생긴다.
- **근거:** `atomic_io.py:19` 직접 열람(고정 tmp), `manager.py:446-449` 직접 열람(uuid tmp과 대조). 폴더 락(비차단·busy 스킵)은 1차 방어이나 전역 분산 락이 아님을 AGENTS가 명시한다.
- **반증 확인:** 폴더 락·검증-선행-쓰기·손상본 거부·원자 replace는 확인했다. 그러나 락 획득 실패 시 스킵이 아니라 락 없이 쓰는 호출자가 있으면 보호가 안 된다. `ConfigManager`가 이미 쓰는 uuid tmp 패턴이 있어 수정 비용이 낮다.
- **호출/영향 범위:** `BackupSyncService.push`·replica 게시·공유 JSON 쓰기 전반. 영향: 다중 PC 공유 폴더.
- **권장 수정 방향:** `write_json_atomic`의 tmp를 `{path}.{pid}.{thread}.{uuid}.tmp`로 교체하고, 성공·실패 시 자기 tmp만 정리한다. 기존 고정 tmp 잔재는 시작 시 무시한다.
- **필요한 회귀 테스트:** 동일 경로에 2 스레드 동시 `write_json_atomic` 200회 → 최종본이 두 입력 중 하나와 정확히 일치하고 tmp 잔재 없음. 중간 판독은 완전한 구버전 또는 완전한 신버전 중 하나.

### [ISSUE-004] NaverCafe 본문 중첩 `<body>`로 잘못된 XHTML

- **위치:** `websync/scrapers/naver_cafe.py:159-173, 198-200`, `websync/epub/builder.py:127-150, 238-266`, `websync/epub/sanitize.py:29-58`
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** API 경로에서 `container = soup.body or soup` 뒤 `str(container)`를 반환하므로 `<body>...</body>` 래퍼가 그대로 기사 HTML이 된다. 모바일 폴백도 `div` 컨테이너라 정상이나 API 경로가 우선이다. `sanitize_body_html`은 `<body>`를 제거·해체하지 않고, 빌더는 챕터 `<body>` 안에 그대로 삽입하므로 중첩 `<body>`의 잘못된 XHTML이 된다.
- **발생 조건:** 카페 API(`contentHtml`)가 있는 공개 글을 수집하고 해당 글이 EPUB에 들어갈 때. 항상 발동하는 구조적 문제다.
- **영향:** EPUB 검사기·일부 e-ink 리더에서 챕터 검증 실패·본문 누락·스타일 깨짐 가능. 수집 자체는 성공하므로 사용자는 나중에야 발견한다.
- **근거:** `naver_cafe.py:159-173` 직접 열람(API 우선·`str(container)` 반환), `builder.py:127-150` 직접 열람(살균된 본문을 챕터 `<body>`에 삽입), `sanitize.py:29-58` 직접 열람(`body` 처리 없음). 요약 HTML 무정화 의혹은 반증됐다(생산자가 `Summarizer._format_summary`에서 escape하므로 현 producers 한정 안전, §5 참조).
- **반증 확인:** 이미지 제거·짧은 본문 스킵·폴백 컨테이너·`sanitize`의 script/on*·`javascript:` 차단은 확인했다. 그러나 `<body>` 래퍼는 어느 단계에서도 정규화되지 않는다. 프레임워크(ebooklib·BeautifulSoup)가 자동 교정한다는 보장도 없다.
- **호출/영향 범위:** `NaverCafeScraper.fetch_articles` → 파이프라인 기사 배치 → `EpubBuilder.build`·`build_digest` → 전 기기 전송본. 영향: 카페 소스 사용자 전체.
- **권장 수정 방향:** 스크래퍼 반환 직전에 `container`가 `<body>`이면 자식 노드만 반환(unwrap)하거나, `sanitize_body_html`에 `<body>`·`<html>` 해체 규칙을 추가한다. 두 곳 중 한 곳에만 둔다.
- **필요한 회귀 테스트:** `<body><p>hi</p></body>` 입력 스크래퍼 후처리 → 출력에 `<body` 없음·`<p>hi</p>` 보존. 빌드된 챕터 XHTML을 XML 파서로 파싱 → 중첩 body 0건·`lxml.etree` 오류 0건.

### [ISSUE-005] 요약 단계 취소 미배선 (번역만 배선)

- **위치:** `websync/pipeline/sync_pipeline.py:65-69`(번역에만 `cancel_requested` 배선), `websync/pipeline/summarizer.py:59-105`(OpenAI·Ollama HTTP 20~30s 블로킹), `websync/pipeline/translator.py:15-34`(30초 예산·취소 체크)
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 파이프라인이 `translator.cancel_requested`만 설정하고 `Summarizer`에는 취소 콜백·데드라인을 전달하지 않는다. 요약 HTTP 중 취소는 다음 기사 경계까지 반영되지 않는다.
- **발생 조건:** AI 요약 enabled + OpenAI/Ollama가 느리거나 멈춘 상태에서 사용자가 취소·종료를 누른 경우.
- **영향:** 취소·종료 drain이 요약 timeout(20~30s)×기사 수만큼 지연된다. 업로드·이력은 아직 없으므로 데이터 오염은 없으나 체감이 나쁘다.
- **근거:** `sync_pipeline.py:65-69` 직접 열람(번역 배선만 존재), `summarizer.py:44-57` 직접 열람(fail-open이나 취소 없음), `translator.py:30-34` 직접 열람(취소·예산 있음)과 대조.
- **반증 확인:** 요약 실패 시 `""` 반환 후 계속되는 fail-open, 기사 경계 취소, 종료 drain 루프는 확인했다. 그러나 진행 중 요약 HTTP 자체를 깨우지는 못하므로 반증되지 않는다. dead code가 아니다.
- **호출/영향 범위:** 전체·선택 파이프라인의 기사 루프 → `Summarizer.summarize` → OpenAI/Ollama HTTP. 영향: AI 요약 사용자.
- **권장 수정 방향:** `Summarizer`에도 `cancel_requested`·기사당 데드라인을 전달하고, HTTP 호출 전후·재시도 사이에 체크한다. 진행 중 소켓 강제 종료는 하지 않는다.
- **필요한 회귀 테스트:** 요약 HTTP를 25초 지연시킨 mock + 시작 1초 후 취소 → 2초 이내에 기사 루프가 `cancelled`로 탈출하고 후속 업로드·이력 0건.

### [ISSUE-006] 응답 유실 시 재전송 (receipt 없음, 설계상 한계)

- **위치:** `websync/upload/uploader.py:117-119`(HTTP 200만 성공), `websync/db/history.py:252-302` 성공분만 기록, `websync/pipeline/sync_pipeline.py` 성공 IP만 mark
- **우선순위:** Medium
- **신뢰도:** Likely(코드 근거 강함, 실기기 재현 없음)
- **문제:** 기기가 파일을 저장한 뒤 응답이 유실되면(타임아웃·연결 끊김·프로세스 종료) 클라이언트는 실패로 기록하고 이력도 남기지 않는다. 다음 실행은 같은 기사를 신규로 보고 다시 보낸다. 기사 집합 hash 파일명이라 배치 구성이 같으면 같은 이름, 다르면 다른 이름의 중복본이 기기에 남을 수 있다.
- **발생 조건:** 저장 후 응답 전 네트워크 단절·기기 재시작·클라이언트 종료가 겹친 좁은 창.
- **영향:** 중복 전송(가용성·용량)이며 기존 파일 파괴가 아니다. 빈도는 낮으나 무선 환경에서 0은 아니다.
- **근거:** `uploader.py:117-119` 직접 열람(200 이외 전부 실패), CodeGraph 확인 `mark_synced_many` 성공 경로 전용 호출. `README`의 응답 유실 한계 서술과 일치하는 방향이다.
- **반증 확인:** 부분 성공 재시도(`only_ips`), 성공분만 기록, 파일명 hash, `check_batch_filenames` 배치 내 중복 거부는 확인했다. 그러나 기기 측 영속과 클라이언트 기록을 묶는 receipt·멱등 커밋이 없으므로 응답 유실 창은 남는다. 프레임워크가 보장하지 않는다.
- **호출/영향 범위:** 전 파이프라인 업로드 → 기기 `/upload` → DB 이력. 영향: 무선 전송 전체.
- **권장 수정 방향:** 단기에는 사용자 문서에 "응답 유실 시 1회 중복 가능"을 유지하고, 중기에는 기기 지원 전제로 idempotent receipt(기기 측 파일 ID·바이트 확인 후 mark) 설계 트랙을 별도 승인받아 진행한다. lease만으로 exactly-once를 주장하지 않는다.
- **필요한 회귀 테스트:** 저장 후 소켓 절단 주입(mock 서버가 저장하고 응답을 끊음) → 재실행 시 중복본 0건·이력 1건(설계 후). 현 계약에서는 중복 1회를 허용하고 2회 이상을 실패로 판정.

## 5. Potential Functional Gaps

- **[Likely Gap] 파이프라인 전체 데드라인 없음.** 기사·이미지·번역·요약·업로드 개별 timeout은 있으나 전체 경과 상한이 없다. 무한 hang 재현은 없으나 장시간 작업에서 종료 예측이 어렵다.
- **[Confirmed Gap] `get_history` 다기기 표시 임의성.** `websync/db/history.py:343-361`이 `GROUP BY url`에 bare `site_name`·`title`을 선택하므로 다기기 행 중 임의 행이 표시된다. 이력 조회 탭 표시 전용이며 재전송 판단에는 쓰이지 않는다.
- **[Confirmed Gap] 대시보드 쿼리스트링 404 비대칭.** `websync/servers/dashboard/handler.py:89-125`가 `self.path` 정확 일치라 `/api/log?x=1`·`/api/status?x=1`은 404다. OPDS는 쿼리를 분리한다. 기능 파손이 아니라 클라이언트 호환성 gap이다.
- **[Confirmed Gap] 정적 분석 게이트 무력화.** `pyrightconfig.json`이 모든 `report*`를 `none`·`basic`으로 끈다. "basedpyright 0 errors" 통과 주장은 vacuous하다. 타입 보장이 아니라 테스트·리뷰 의존 상태다.
- **[Likely Gap] macOS 실런타임·네이티브 CI 미확인.** launchd 등록·해제·plist 보존 로직은 코드로 확인(§3)했으나 실 macOS 데몬 E2E·네이티브 CI 결과는 본 세션에서 확인하지 못했다.
- **[추정] 장기 보존 정책 없음.** `scripts/storage_report.py`·`watch get_stats`는 관측 수단만 있고 임계치·자동 정리 정책은 없다. 의도적 보존 정책일 수 있어 버그로 단정하지 않는다.
- **[추정] 요약 HTML 이중 `<blockquote>` 미관.** 합본 경로(`builder.py:241-246`)가 이미 `<blockquote>`인 요약에 한 번 더 감싸는 구조다. 현 producers는 escape되므로 XSS가 아니라 미관·파서 관대성 영역이다.
- **반증되어 제외한 것:** `summary_html` 미정화(XSS) 의혹 — 현 생산자(`Summarizer._format_summary`, `summarizer.py:40-42`)가 escape하므로 live 결함이 아니다. 방어적 정화로만 권고한다. `device_client` finally 미바인딩 의혹 — 2차 try 구조상 항상 바인딩되어 성립하지 않는다. shell(`shell=True` 0건)·SQL(플레이스홀더 전용)·주요 경로 traversal(basename+realpath+normcase+테스트)은 코드·테스트 대조로 반증됐다.

## 6. Documentation Mismatches

중대 불일치는 확인하지 못했다. 아래는 경미한 사항이다.

- `websync/__init__.py:3`은 `1.4.1`이나 `README.md:71` 다운로드 예시는 구버전 파일명을 예시로 든다. 다운로드 링크가 `/releases/latest`라 실질 영향은 없다.
- `CLAUDE.md`·`AGENTS.md`는 제목·정본 안내 2줄을 제외하고 본문이 일치한다.
- `USER_GUIDE.md` 다운로드 충돌 서술(거부 시 보존·실패)은 `publish_local_download` 기본 정책과 일치한다.
- `docs/AUDIT_IMPLEMENTATION.md`의 "basedpyright 0 errors" 서술과 `pyrightconfig.json`(전면 `none`)의 조합은 게이트 유효성 측면에서 오해를 부른다. 타입 검사가 통과했다는 서술 자체는 거짓이 아닐 수 있으나, 검사 강도가 사실상 꺼져 있어 보증으로 읽기 어렵다. 문서·게이트 중 하나를 고쳐야 한다.
- `README`·`CLAUDE`·`AGENTS` 전문 대조는 하지 않았으므로 "불일치 없음"을 전수로 주장하지 않는다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate (데이터·주요 실패, 코드 변경 필요)

1. ISSUE-001: 일시 오류 제한 재시도(1~2회·백오프) + 취소 이벤트 전파(다음 IP·다음 배치 중단). 진행 중 POST 강제 종료는 하지 않는다.
2. ISSUE-002: `local_import` 폴백을 CAS 준수로 교체(재독·재병합 후 `expected_revision` 저장, 실패 시 미저장·경고).
3. ISSUE-004: NaverCafe `<body>` 정규화(스크래퍼 또는 `sanitize` 중 한 곳).

실제 코드는 수정하지 않았다.

### Phase 2 — Stability (예외·검증·재시도·상태·호환성)

4. ISSUE-005: 요약 취소·데드라인 배선(번역과 대칭).
5. ISSUE-003: 공유 쓰기 uuid tmp 교체.
6. `get_history` 표시 확정성(`MAX(synced_at)` 행의 `site_name`·`title`을 서브쿼리로 고정) 또는 표시 전용임을 주석화.
7. 대시보드 쿼리 분리(OPDS와 대칭) 또는 쿼리 포함 경로를 404가 아니라 정상 처리.
8. `pyrightconfig.json` 규칙 상향 또는 "타입 게이트는 형식적"임을 문서에 명시.
9. macOS 토스트 이스케이프를 백슬래시까지 처리(영향은 self-exec Low이나 수정 비용이 낮음).

### Phase 3 — Structural (구조·테스트 가능성·책임 분리)

10. ISSUE-006: 기기 지원 전제로 idempotent receipt 설계(별도 승인 필요). lease만으로 exactly-once를 주장하지 않는다.
11. 파이프라인 전체 데드라인·진행 상태 계약(개별 timeout과 별개 상한, 취소 지연 SLO 문서화).
12. 보존 정책 결정(임계치·자동 정리 vs 관측만 유지).
13. 문서 문자열 고정 테스트(`test_documentation_encoding.py`)의 과민 고정 완화(핵심 문구만 pin).

## 8. Test Recommendations

단순 "테스트 추가"가 아니라 입력 조건과 기대 결과를 명시한다.

- **Unit — 업로드 재시도:** `requests.post`가 `ConnectionError` 1회 후 200을 반환하도록 주입하고 `upload_to_targets` 호출 → 결과 `{ip: True}`, POST 2회, `last_errors` 비어 있음.
- **Unit — NaverCafe body:** `contentHtml="<body><p>hi</p></body>"` mock API → 스크래퍼 출력에 `<body` 없음·`<p>hi</p>` 있음. 빌드 챕터를 `lxml.etree`로 파싱 → 오류 0건.
- **Unit — 요약 escape 유지:** `Summarizer._format_summary('<script>x</script>\nA&B')` → 출력에 `<script` 없음·`&lt;script` 있음·`<br/>` 있음.
- **Unit — get_history 확정성:** 동일 URL에 기기 A·B 다른 제목으로 기록 후 `get_history` 반복 호출 → 동일 행 반환(또는 최신 행 반환으로 명세 고정).
- **Integration — 설정 경합:** `update_config` 1회 실패 주입 + 병행 writer revision 상승 상태에서 `local_import` 실행 → 병행 변경 보존·병합분 추가·revision 단조 증가.
- **Integration — 공유 쓰기 경합:** 2 스레드 동시 `write_json_atomic` 200회 → 최종본이 입력 중 하나와 완전 일치·tmp 잔재 0건.
- **Integration — E2E 소스→기기:** A글 1·B글 2 이력 사전 기록, B 전송 1회 실패 주입 후 재시도 → 2차 실행은 미전송분만 포함·성공분만 기록·부분 실패 상태 `False`.
- **Concurrency — 취소:** 요약 25초 지연 mock + 1초 후 취소 → 2초 내 `cancelled`·업로드·이력 0건. 대용량 업로드 timeout 축소 mock + 전송 중 취소 → 다음 배치 경계에서 종료·진행 스레드 정리.
- **Concurrency — 종료 drain:** 파이프라인 실행 중 `_on_close` → 신규 작업 거부·진행분 commit·pending 보존·backup flush 후 종료.
- **Regression — 공유 손상:** 손상 JSON·0바이트·미완성 파일 입력 → `JsonReadError`·원본 보존·전송 중단. push 실패 → 전송 전 중단·원본 보존.
- **Regression — 응답 유실:** 저장 후 응답 절단 mock → 현 계약에서는 중복 1회 허용·2회 이상 실패, 설계 후에는 중복 0건·이력 1건.
- **Platform-specific — Windows:** 261자 초과 경로 등록 거부·`last_error` 표시, OEM 출력 디코딩 깨짐 없음. **macOS:** unload 실패+job 잔존 → `False`·plist 보존. **Linux:** `%`·공백·작은따옴표·백슬래시 포함 경로의 shlex 왕복 + 가짜 sync 1회 실행.
- **Security — 서버:** 토큰 없음·과대 body·탈출 경로·동시 sync → 401·400·403·409. **업데이터:** hash·크기 불일치·교체 중단·smoke 실패 → 기존 exe 보존·rollback.

## 9. Final Assessment

- **Functional Correctness: Acceptable.** 핵심 수집·중복 제거·EPUB·전송·부분 실패 처리는 확인했다. 잔여는 예약·실환경 조건부(ISSUE-001/004/005)다.
- **Runtime Stability: Acceptable.** 공통 락·취소·drain·개별 timeout은 확인했다. 전체 상한·실플랫폼 장시간 검증은 남았다.
- **Data Integrity: Acceptable.** DB PK·트랜잭션·설정 원자 저장·다운로드 배타 게시는 확인했다. ISSUE-002/003은 좁은 경합창이며 ISSUE-006은 중복 전송이지 파괴가 아니다.
- **Error Resilience: Acceptable.** 사이트별 계속·backup pull/push 실패 중단·부분 전송·업데이터 rollback은 확인했다. 재시도 부재(ISSUE-001)가 체감 복원력을 낮춘다.
- **Cross-platform Robustness: Needs Work.** Windows·Linux 스위트는 본 세션 60 passed로 확인했으나 macOS 실데몬·Linux 실데몬·실기기 검증은 하지 못했다.
- **Test Confidence: Acceptable.** 본 세션 60 passed + 격리·보안·회귀 테스트 존재를 확인했다. 전체 스위트·frozen·optional 의존성 런타임은 미실행이므로 상한을 두지 않는다.

**실제로 먼저 수정할 문제 3개:**

1. ISSUE-001 업로드 재시도·취소 전파 — 체감 실패율과 직결된다.
2. ISSUE-002 `local_import` 폴백 CAS 준수 — 설정 회귀를 막는다.
3. ISSUE-004 NaverCafe 중첩 `<body>` — EPUB 무결성을 해친다.

## 10. 후속 조치 (2026-11-21 구현 기록)

위 진단은 수정 전 상태를 기록한 것이다. 같은 날 아래를 구현하고 회귀 테스트로 고정했다.

- EPUB 무결성(실기기 "잘못된 책" 원인): `sanitize_body_html`이 HTML 주석을 제거한다(네이버 `SE-TEXT` 주석이 ebooklib 0.21 nav 생성을 터뜨려 `nav.xhtml` 없는 부분 zip이 남던 문제). `EpubBuilder.build`·`build_digest`는 `write_epub` 실패 시 예외를 발생시켜 깨진 책이 전송·기록되지 않는다. 오늘 생성분 중 깨진 네이버 3권의 실제 챕터로 재빌드해 `nav.xhtml` 복구를 확인했다.
- ISSUE-001: 일시 오류(Timeout·연결 끊김·429·5xx) 제한 재시도 + 취소 전파(대기 전송 스킵·재시도 중단, 진행 중 POST는 강제 종료하지 않음). 파이프라인·선택 전송에 취소 콜백을 배선했다.
- ISSUE-002: `local_import` 폴백도 디스크 재독·재병합 후 CAS 저장, 실패 시 미저장으로 변경했다.
- ISSUE-003: 공유 JSON tmp를 호출별 고유 경로로 변경했다.
- ISSUE-005: 요약기에 번역기와 같은 취소·기사당 예산을 배선했다.
- ISSUE-006: 응답 유실 계약을 사용자 문서에 명시하고 fake 서버 저장-후-절단 모드로 회귀 테스트를 고정했다.
- Gaps: 대시보드 쿼리스트링 라우팅, `get_history` 최신행 확정, macOS 토스트 이스케이프, 실패 사이트 안내 대화상자·재시도(`failed_sites` 결과 포함).
- 검증: 영향 범위 239 passed, pyright 0 errors, ruff clean.
- 남은 범위: 원격 receipt 설계(별도 승인 필요), 실기기·실스케줄러 E2E, 전체 스위트·frozen 검사는 릴리즈 CI에서 수행한다.
