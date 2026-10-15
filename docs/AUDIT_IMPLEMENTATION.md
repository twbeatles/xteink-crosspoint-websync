# Audit Implementation

최신 후속 기록: [2026-10-15 후속 구현](#2026-10-15-후속-구현). 아래 2026-10-13 기록은 당시 실행·릴리즈 이력으로 보존하며 현재 검증 결과로 재사용하지 않는다.

2026-10-13 — PROJECT_AUDIT.md 후속 구현 및 검증 기록.

## 완료한 수정

| 감사 항목 | 구현 | 검증 |
|---|---|---|
| ISSUE-001 / 백업 변경 유실 | 최신 config transaction 안에서 사이트·삭제 표식 병합. 반환된 snapshot 게시. push/pull 진행 중 include_history 변경은 검증된 component set 유지 | test_backup_config_concurrency.py: 독립 writer의 추가/편집/삭제/재등록 및 옵션 변경 |
| ISSUE-004 / 테스트 격리 | import 전 X3_WEBSYNC_STORAGE_ROOT 주입, 테스트별 DB/log/output/sidecar/lock 격리. Python 파일·SQLite URI·dir_fd 접근 guard. service/builder 의존성 주입 | test_storage_isolation.py: synthetic sentinel, subprocess, URI/Windows 확장 경로 및 POSIX descriptor 보호 |
| ISSUE-002 / 번역 | googletrans>=4.0.2,<5 async adapter. HTML별 client/event loop 수명 관리, auto source, await와 close. 기존 async host에서는 별도 worker loop | test_translator.py, test_googletrans_contract.py: async stub 및 설치된 4.0.2의 fake HTTP transport |
| ISSUE-003 / 취소 | 성공적으로 수락된 작업만 새 취소 scope로 시작. busy 요청은 현재 취소 유지. preview/selected/EPUB-only 공통 락, 예외 결과 상태 갱신 | test_job_lifecycle.py, 기존 selected/preview/service 테스트 |
| 종료·재실행 | 새 작업 수락 중지 → 서버/Watch 정지 → 자기 워커·commit 대기 → backup flush → Tk destroy. GUI thread는 after polling으로 유지하며 다른 CLI process의 락을 기다리지 않음 | 느린 worker barrier + 실제 SQLite commit 후 root destroy; async 예외/락 해제 |
| 대시보드 HTTP | HTTP/1.1 + 정확한 Content-Length, 모든 POST의 bounded body 소비, malformed request 거부. bounded graceful close, Windows exclusive bind. mutation 자동 재시도 제거 | body 없음/JSON 반복 POST callback 횟수, 401/409/cancel, malformed length, 기존 HTTP/OPDS 계약 |
| 대시보드 사용자 기능 | 취소 버튼, 상태 기반 버튼 활성화, 상태·로그 5초 polling, fetch timeout 및 응답 불확실성 안내 | template/API 계약. 실제 브라우저 도구는 연결된 browser가 없어 미실행 |
| 오프라인 이미지 | include_images 기사에 PNG/JPEG/GIF를 EPUB item으로 포함. 상대 URL 해석, SHA-256 content dedup, image/book/count budget, private-host 제한. 실패 시 alt text | per-site/digest ZIP manifest·asset·XHTML 확인, unsupported/oversize/private image 거부 |
| 클라우드 복제본 충돌 | .websync-replicas의 설치별 snapshot과 canonical JSON 병합. URL별 최신 변경·삭제 표식, 이력 resend/tombstone 정리. 다른 PC에 복사된 config의 writer ID 재생성 | 서로 다른 local replicas의 canonical overwrite 후 데이터 수렴, corrupted snapshot fail-closed, symlink boundary |
| 파일명 문서 불일치 | 기기 전송 이름은 ASCII 문자와 원래 basename hash 사용. EPUB title은 원래 언어 유지 | 날짜·확장자·ASCII·한글 원본 사이의 고유성 |
| 플랫폼·배포 | Linux/Windows/macOS × Python 3.10/3.15 계약 CI, optional translation CI, isolated frozen build script/job, 새 모듈 hiddenimports | Windows에서 actual frozen build 및 --smoke 통과. Linux/Windows/macOS × Python 3.10/3.15 CI 계약 모두 통과 |

## 사용자 계약

- 한 번 수락된 동기화·선택 전송·미리보기·EPUB 생성은 같은 파이프라인 락을 사용한다. 취소 후 새 작업은 독립적으로 실행된다.
- 종료 요청은 진행 중 HTTP 요청 자체를 강제로 끊지 않는다. 현재 작업이 정리되고 성공 이력이 기록될 때까지 창과 Tk event loop를 유지한다. Watch에서 아직 전송하지 못한 파일은 pending_files에 남아 재시작 시 다시 처리한다.
- 정상 종료는 처리 중 워커의 DB commit과 backup flush를 기다린다. 강제 process kill/전원 손실 또는 기기가 전송을 완료한 뒤 응답을 잃은 경우는 분산 transaction으로 보장하지 않으며, 실패/불확실 상태에서는 재전송될 수 있다. 사용자 이력을 추정해서 성공 처리하지 않는다.
- 이미지 포함은 기존 사이트별 옵션으로 활성화한다. 지원 raster 형식은 PNG/JPEG/GIF, 이미지당 4MiB, book 전체 24MiB, URL 수 32개다. 새 이미지 fetch 시작 budget은 30초이며 진행 중 요청은 HTTP timeout/retry 정책에 따라 마친다. 원격 srcset은 제거한다. 이미지 포함을 끈 기사는 scraper가 이미지 태그를 제거한다.
- EpubBuilder를 직접 호출하는 개발자는 article에 include_images=True와 URL을 제공해야 offline packaging을 요청할 수 있다. Pillow는 표지 생성용 선택 의존성이고 raster embedding에는 필요하지 않다.
- 일반 OneDrive/Dropbox/Google Drive 로컬 복제 폴더의 파일 락은 PC 사이의 전역 전송 락이 아니다. 설치별 snapshot은 동시 게시의 변경 보존·사후 수렴을 제공한다. **같은 reader로 자동 전송하는 PC는 하나만 활성화하고 다른 PC는 전송 전 공유 동기화 완료를 기다린다.** 여러 PC의 동시/offline 전송을 정확히 한 번으로 보장하려면 별도 server CAS/lease가 필요하며 이번 구현에서 제공한다고 주장하지 않는다.
- canonical sites.json/synced_posts.json은 유지한다. 공유 폴더의 .websync-replicas도 함께 동기화해야 한다. 설치별 UUID는 local config에 저장되고 PC 이름은 local config에만 남는다. 단일 설치의 snapshot을 갱신하며 128개를 넘는 snapshot은 fail-closed한다. 이전 설치 snapshot을 제거할 때는 모든 기록이 canonical 정본에 반영된 뒤에만 사용자가 정리한다.
- 잘못된 replica JSON/경로는 local config/DB mutation 전에 거부한다. include_history를 끄면 새로운 이력을 export하지 않으며 이미 공유된 이전 이력을 삭제하지 않는다.
- 테스트 보호 장치는 Python 파일/SQLite I/O 경계이며 OS sandbox가 아니다. 임의 외부 실행 파일에 대한 격리를 보장하지 않는다. native integration은 disposable runner 또는 별도 sandbox에서 수행한다.

## 테스트 권고 대응표

| 보고서 권고 | 확인하는 파일/흐름 |
|---|---|
| Unit / 번역, input validation | test_translator, test_googletrans_contract, test_config_validator, test_scraper_limits |
| Integration / config concurrency, backup 실패 | test_backup_config_concurrency, test_backup_service, test_backup_crash_consistency, test_backup_atomic_io |
| End-to-End / scrape→EPUB→HTTP→history | test_pipeline_http_integration, test_pipeline_failure_recovery, test_epub_structural_contract |
| Cancellation / close / restart | test_job_lifecycle, test_gui_user_journey, test_service, test_selected_sync, test_watch_calibre |
| Concurrency / multiprocess / multiple readers | test_pipeline_multiprocess_lock, test_config_manager, test_multi_pc_history, test_multi_pc_pipeline, test_backup_interleavings |
| Cloud replica delay/corruption | test_cloud_replica_recovery |
| DB migration / rollback / deletion / resend | test_db, test_history_state_machine, test_backup_service |
| HTTP transport / auth / traversal / file failures | test_dashboard_request_contract, test_http_server_lifecycle, test_opds_security_contract, test_crosspoint_http_contract, test_crosspoint_upload_failure_matrix, test_device_client_branches |
| Content encoding/markup / offline image | test_scraper_sanitization, test_scraper_metamorphic, test_epub_offline_images, test_epub_structural_contract |
| Paths / native adapter quoting / Calibre | test_device_path_properties, test_scheduler, test_calibre, test_paths |
| updater signature/hash/cancel/rollback / frozen | test_update_manifest, test_update_installer, test_update_service, test_updater_cli, test_release_frozen_contract, scripts/verify_isolated_build.py |

기존 테스트와 새 회귀 테스트를 함께 사용한다. 실제 사이트·기기·네이티브 GUI 정상성을 mock/loopback 통과만으로 보장하지 않는다.

## 실행 가능한 검증

```powershell
python -m pytest tests/ -q --tb=short
python -m pytest tests/test_translator.py tests/test_googletrans_contract.py -q -W error::RuntimeWarning
python scripts/verify_isolated_build.py
```

coverage 실행 시 COVERAGE_FILE을 임시 경로로 지정한다. 사용자 config.json/sync_history.db가 있는 root에서 smoke를 실행할 때도 X3_WEBSYNC_STORAGE_ROOT를 임시 경로로 지정해 테스트 데이터를 분리한다.

## 실제 검증 결과

- 전체 suite: **528 passed, 1 skipped**, exit 0, Windows / Python 3.15.0, 74.88초. 한국어 문구와 문서 UTF-8 회귀를 포함한다.
- 분기 포함 전체 coverage: **55%** (직전 522개 테스트 실행에서 측정). 실제 native GUI와 외부 서비스 검증을 의미하지 않는다.
- 마지막 pull 옵션 경합 추가 후 backup/multi-PC 묶음: **41 passed**.
- 무재시도 HTTP/OPDS 묶음: **19 passed**.
- 실제 frozen EXE를 임시 source/work/dist에서 빌드하고 --smoke exit 0 확인. 사용자 dist나 config/DB를 사용하지 않는다.
- 코드 commit 774ddcd의 [GitHub Actions](https://github.com/twbeatles/xteink-crosspoint-websync/actions/runs/38354390596)는 **12개 job 모두 성공**: unit-linux, contract-linux, integration-windows, coverage, OS/Python 조합 6개, optional-translation, frozen-smoke.
- Linux/Windows/macOS × Python 3.10/3.15의 계약은 실제 CI runner에서 실행했다. native scheduler 등록·GUI 실사용·실기기 검증은 별개다.
- 실제 config.json, config.json.bak, sync_history.db SHA256은 수정 시작 전 값과 모두 동일하다. 감사 이전 이력 상태를 추정 복구하지 않았다.
- 브라우저 inventory가 비어 있어 실제 UI 조작은 미실행. 로컬 mock 서버는 정지했다.
- PowerShell 파이프에서 새 한국어 문구가 물음표로 바뀐 부분을 UTF-8로 다시 저장하고, ko/en 렌더링 문구 회귀를 추가했다.
- ISSUE-001/002/003/004 수정 완료. 테스트 권고는 기존 계약과 새 회귀의 대응표로 정리했고 외부 확인은 아래 별도로 남긴다.

## 외부 확인 항목

- 실제 X3/X4 EPUB 표시, Korean EPUB title와 ASCII 파일명, offline raster 이미지, 파일 API의 완료/덮어쓰기 의미.
- 실제 cloud client의 동기화/충돌 파일 정책. snapshot 디렉터리가 숨김 폴더라는 이유로 제외되지 않는지 확인.
- macOS/Linux native scheduler/notification 및 네이티브 GUI close; CI matrix는 계약을 검사하지만 실사용 환경을 대체하지 않는다.
- 실제 Calibre 서재, 외부 scraper 사이트, YouTube, AI 및 번역 provider 네트워크. 이번 로컬 검증은 synthetic 데이터와 mock transport/loopback만 사용.
- 실제 브라우저 login/start/cancel/polling. browser inventory가 비어 있어 자동 UI 조작은 실행하지 못함.

코드·테스트·문서·CI 개선은 위 범위에서 처리했다. 외부 확인 항목은 실행 환경이 필요하며 통과했다고 기록하지 않는다.

검증한 최신 EXE: build/verified-audit-utf8-20261013/x3_websync.exe. 사용자 데이터가 있는 기존 dist는 변경하지 않았다.

## v1.3.2 배포 준비

이 문서의 12개 작업 결과는 감사 개선 당시의 실제 검증 기록이다. 이후 일반 CI는 Linux / Python 3.15 전체 테스트와 Windows / Python 3.10 핵심 계약, 총 2개 작업으로 줄였다. Linux 작업에서 googletrans 4.0.2 계약을 함께 실행한다. Windows 전체 테스트와 frozen EXE 빌드·smoke 및 서명 매니페스트 생성은 릴리즈 태그 워크플로에서 수행한다. macOS 정기 매트릭스와 coverage 작업은 제거했으며, 과거 통과 결과는 위 기록에 남긴다.

[v1.3.2 릴리즈 노트](releases/v1.3.2.md)에 사용자에게 영향이 있는 변경 사항과 클라우드 동시 전송의 범위를 정리했다.

## v1.3.2 게시 검증

- `a47b498`의 간소화된 [Tests CI](https://github.com/twbeatles/xteink-crosspoint-websync/actions/runs/38360935777): Linux 전체 테스트와 Windows 핵심 계약 **2개 작업 모두 성공**.
- 로컬 Windows / Python 3.15 전체 테스트: **528 passed, 1 skipped**. 별도 임시 source/work/dist에서 `v1.3.2` EXE 빌드와 `--smoke` 성공.
- 태그 `v1.3.2`의 [Release CI](https://github.com/twbeatles/xteink-crosspoint-websync/actions/runs/38361105350): Windows 전체 테스트, 키 검증, PyInstaller 빌드·smoke, 릴리즈 및 `updates/latest.json` 게시 단계 모두 성공.
- [GitHub Release v1.3.2](https://github.com/twbeatles/xteink-crosspoint-websync/releases/tag/v1.3.2)는 최신 릴리즈다. 게시된 EXE 크기는 **28,046,709 bytes**, SHA-256은 `4876c91ab71723ea83f19bb09b7382376c1cf99001967d843acb025e3f694928`이다.
- `updates/latest.json`은 `84c71cf`에서 자동 갱신됐다. 내장 공개키로 Ed25519 서명을 검증했고 매니페스트의 버전·URL·크기·해시가 게시된 EXE 메타데이터와 일치한다. 매니페스트 자체의 SHA-256도 게시 자산과 동일한 `d1a164b9656535c4eeea2f202ac4c15521d810ef82af28f40bfcae92a228eb0a`이다.

로컬에서 빌드한 EXE는 릴리즈 러너에서 빌드한 EXE와 바이트 단위 재현성을 주장하지 않는다. 위 공개 해시는 릴리즈 러너가 게시한 자산의 값이다.

## 2026-10-15 후속 구현

대상은 [2026-10-15 감사](../PROJECT_AUDIT.md)다. Spec Kit 없이 진행했다. 사용자 승인 범위는 로컬 앱 수정·명시적 복구·재시도·테스트 완료 및 중앙 서버 확장의 설계·검증 절차다. 서버 코드를 추가하거나 실제 기기·사용자 설정·DB를 변경하지 않았다. 아래 완료는 이 범위의 구현 완료이며 모든 외부 환경 검증을 끝냈다는 의미가 아니다.

### 구현 결과

- **ISSUE-001:** 사이트 import를 전체 사전 검증한다. 타입 안전한 구조화 오류 `field/code/message` 및 기존 문자열 API를 제공하고 config load/save/RMW·backup 입력 경계도 보호한다. 실패한 import는 bytes·revision·`.bak`을 변경하지 않는다. GUI 기동 복구와 `--recover-config JSON`은 명시적으로 정상 전체 설정을 선택하고 원본 `.rejected.<id>.json` 및 기존 `.bak`을 보존한다. 과거 의미적 warning은 기동 불가 구조 오류와 구분한다.
- **ISSUE-002:** 로마자 prefix와 별도로 변환 전 원본 basename hash를 계산한다. 배치 내 결과 전송명은 대소문자 무시 비교로 사전 검사한다. 기존 ASCII 이름 동작은 유지한다. 비ASCII 새 전송명과 옛 기기 파일은 공존할 수 있고 자동 이관·삭제는 없다. 유한 hash의 모든 가능한 입력에 대한 무충돌을 보장하지 않는다.
- **ISSUE-003:** 소스 URL 기반 ID를 이름과 분리해 전체 합본·preview·선택·EPUB-only로 전달한다. 이름 변경에는 ID가 유지되고 URL 변경에는 바뀐다. 현재 config의 소스별 번역 옵션을 적용하고 이름만 가진 옛 선택이 모호하면 미리보기를 다시 실행하도록 요구한다. 실제 EPUB ZIP·HTTP·SQLite 통합 회귀를 추가했다.
- **Watch:** `pending_jobs`에 내용 fingerprint·대상·성공 대상을 영속화하며 `pending_files`도 호환한다. 2초부터 최대 300초까지 지수 backoff로 새 이벤트 없이 재시도한다. 같은 내용/대상 폴더의 성공은 제외하고 내용 변경·새 대상·폴더 변경은 새 전송으로 처리한다. 중지·파일 안정화·중복 이벤트·저장 실패·missing 파일 복귀·재기동을 다룬다. 서버/기기 receipt가 없어 HTTP 완료/응답 유실 경계의 exactly-once는 보장하지 않는다.
- **배포·문서:** config_recovery/sources/retry hiddenimports를 명시하고 README 양 언어·CLAUDE·사용자/개발 가이드와 선택 의존성 주석을 갱신했다. 기존 감사 본문·과거 실행 기록은 보존하고 현재 상태 링크를 붙였다. 경량 EXE의 optional 의존성 제외 정책은 유지한다.

### 감사 권고 전체 대조표

| 감사 항목 | 상태와 구현/근거 | 검증 또는 후속 절차 |
|---|---|---|
| Phase 1.1 / ISSUE-001 / Unit·Integration·Regression 설정 입력 | 구현 완료: validator, ConfigManager의 저장 전 검사·전체 거부 | `test_config_input_recovery.py`: null/배열/숫자/CSS/limit/URL, 혼합 import, bytes·bak·revision·다시 load, save/RMW/load 경계 |
| Phase 1.2 / ISSUE-002 / 파일명 Unit·Integration | 구현 완료: 원본 hash·배치 preflight·호환 정책 | `test_uploader_sanitize.py`: 로마자 충돌/악센트 쌍·ASCII 호환·같은 basename·casefold; `test_upload_batch_preflight.py`, `test_crosspoint_http_contract.py`, `test_crosspoint_upload_failure_matrix.py`: fake 파일 API·payload·실패. 실기기 두 파일 보존/대체 의미는 외부 절차 |
| Phase 2.1 / ISSUE-003 / 합본 E2E | 구현 완료: URL ID·표시 이름 분리 | `test_pipeline_http_integration.py`: 같은 이름 두 feed의 두 ZIP 본문·HTTP 전송·실제 DB·no_new, 비대칭 이력·부분 실패·재시도 |
| Phase 2.2 / Phase 3.2 / 구조화 validation | 구현 완료: `ValidationIssue(field, code, message)`와 문자열 호환, backup의 검증 경계 | `test_config_input_recovery.py`, `test_config_validator.py`, 기존 `test_backup_service.py` |
| Phase 2.3 / Watch Gap / retry Unit·Integration | 구현 완료: durable 부분 성공·재시도·stability·종료 | `test_watch_retry.py`, `test_watch_calibre.py`: 이벤트 없는 복구·부분 성공·중복·중지/재시작·내용/폴더/대상 변경·actual observer handler |
| Phase 2.4 / native·device·cloud 검증 | 로컬 frozen 검사 완료, 외부 절차 문서화 | `scripts/verify_isolated_build.py`; 실제 X3/X4·클라우드 client·native scheduler/GUI는 [opt-in 절차](AUDIT_VALIDATION.md)로 분리. 이번 실행 성공 주장 없음 |
| Phase 3.1 / stable source model | 구현 완료: `pipeline/sources.py`·preview metadata·현재 번역 설정 | `test_selected_sync.py`: 모호한 legacy 거부·rename/URL 대소문자; `test_pipeline_http_integration.py`: selected/EPUB-only·merge mode·소스별 번역 |
| Phase 3.3 / fixture와 외부 검증 분리 | 문서화 완료, 기존 tooling 재사용 | `AUDIT_VALIDATION.md`, `scripts/validate_korean_scrapers.py`, `scripts/verify_isolated_build.py`; 외부 검증 전용 중복 도구·dependency 설치 없음 |
| Gap: 설정 복구 UX | 구현 완료: GUI 선택/취소·CLI 복구 | `test_config_input_recovery.py`: 잘못된 복구 불변·bak 보존·GUI 정리·CLI 성공/실패 |
| Gap: PC 간 정확히 한 번 전송 | 승인 범위의 설계 완료, 서버/firmware 미구현 | `AUDIT_VALIDATION.md`: lease/CAS/fencing/outbox·artifact ID·기기 receipt, 두 client/partition/crash 검증 수락 조건 |
| Gap: 응답 유실 뒤 원격 완료 조정 | 로컬 실패/불확실 처리 유지, 프로토콜 설계 완료 | `test_pipeline_failure_recovery.py`, `test_crosspoint_upload_failure_matrix.py`; true exactly-once는 원격 receipt 없이는 불가. 설계의 commit 경계 재현 절차 |
| Gap: 외부 서비스 장기 호환성(추정) | 실제 장애로 분류하지 않음, opt-in live 절차 완료 | 기존 live scraper validator와 provider/Calibre 테스트 계정 절차; 실제 외부 호출 미실행 |
| 문서 불일치 1: basename hash | 구현과 현재 문서 정합화 완료 | README/README.ko/CLAUDE/가이드의 원본 hash·전환 정책, 기존 감사 당시 설명은 역사로 유지 |
| 문서 불일치 2: 구조·이미지 정책 | CLAUDE 본문 수정 완료 | romanize/original hash와 `include_images` 조건 설명. 사용자 제공 untracked AGENTS.md는 수정하지 않음 |
| 문서 불일치 3: googletrans 주석 | 수정 완료 | requirements.txt 주석을 optional의 `>=4.0.2,<5`와 일치시킴. 구버전 의존성 설치 없음 |
| Concurrency: 설정 | 기존 lock/revision 및 새 사전 검증으로 실패 원자성 보호 | `test_config_manager.py`, `test_backup_config_concurrency.py`, `test_config_input_recovery.py`. 정상 writer 간 경합과 잘못된 입력의 무변경은 각각 자동 검증 |
| Concurrency: 작업 수락·취소 | 기존 보호·회귀 유지 | `test_pipeline_multiprocess_lock.py`, `test_job_lifecycle.py`, `test_dashboard_request_contract.py`: 중복 수락 거부·busy가 취소 보존·다음 작업 정상 |
| Integration: HTTP 후 DB 실패·worker 예외 | 기존 failure 결과·lock 해제 계약 유지 | `test_pipeline_failure_recovery.py`, `test_crosspoint_upload_failure_matrix.py`; 원격 결과 추정 성공 기록 금지, 중복 가능성 문서화 |
| E2E: 느린 작업 중 종료 | 기존 drain 유지 + Watch 중지 보완 | `test_gui_user_journey.py`, `test_job_lifecycle.py`, `test_watch_retry.py`: commit 대기·미완료 보존. 실제 native 창 조작은 별도 절차 |
| Integration: 공유 JSON/replica/tombstone | 기존 fail-closed·수렴 검증 유지 | `test_cloud_replica_recovery.py`, `test_backup_interleavings.py`, `test_backup_service.py`, `test_history_state_machine.py`; 실제 cloud client는 별도 |
| Platform Windows / Linux/macOS | adapter·경로 계약 유지, frozen 실검증 | `test_scheduler.py`, `test_paths.py`, `test_release_frozen_contract.py`; 실제 native 등록/해제는 disposable 계정 절차 |
| Native X3/X4 E2E | 외부 검증 절차 완료, 실기기 미실행 | 빈 테스트 폴더에서 충돌 쌍·날짜 합본·이미지·다운로드 hash·overwrite 결과 기록 |
| Browser E2E | HTTP/template 계약 유지, synthetic Chromium 실검증 | `test_dashboard_request_contract.py`, `test_http_server_lifecycle.py`; login→sync→poll→409→cancel·응답 유실 복구의 결과는 아래 기록 |

각 행의 테스트는 범위 대응 근거다. mock/loopback 통과를 실제 기기·클라우드·native E2E 성공으로 치환하지 않는다. 기존 테스트의 넓은 계약과 이번에 새로 재현한 경계 사례를 구분한다.

### 실제 검증 근거

- Phase 1 commit `d7140b5`: 설정 입력/복구와 파일명 보호.
- Phase 2 commit `645e55c3250239f08035f5d7bff0c099a74f9c6a`: 소스 identity/합본·선택과 durable Watch. 로컬 전체 suite **620 passed, 1 skipped**, 100.47초. 이 수치는 Phase 2 완료 당시 결과다.
- 최종 spec의 새 hiddenimports를 포함해 `python scripts/verify_isolated_build.py` **exit 0**, `Isolated frozen build and --smoke passed`. 임시 source/work/dist/state에서 실제 frozen EXE를 빌드·실행했으며 기존 사용자 dist를 사용하지 않았다.
- 설치된 Chromium을 Playwright headless로 실행한 synthetic loopback dashboard 검사 **exit 0**: 미인증 API 401, 잘못된 토큰 거부, login→sync→5초 polling→cancel, 중복 409, 서버가 수락한 POST의 응답을 의도적으로 버린 뒤 불확실성 안내·상태 회복·cancel. start callback 2회, cancel 2회, poll 6회, JS page error 0. CUA 연결은 사용할 수 없었고 headless-shell은 환경의 SIGILL로 실행되지 않았으나 설치된 전체 Chromium 실행은 성공했다. 최초 harness의 logger 정리 실패(exit 1)는 정리 코드를 바로잡아 재실행 exit 0으로 확인했다. 브라우저·서버·thread·logger를 종료하고 해당 임시 폴더만 정리했다. 실제 기기·외부 서비스·native Tk GUI 검증은 아니다.
- 최종 현재 소스·문서·spec 회귀 검사: `python -m pytest -q -o faulthandler_timeout=60` **exit 0, 620 passed, 1 skipped**, 85.76초. storage guard와 session cleanup도 통과했다. synthetic HTTP 연결 reset의 stderr 출력은 있었으나 실패 테스트는 없었다. 결과 문서 반영 후 문서 UTF-8·frozen 계약 대상 검사도 **10 passed**, 3.39초이며 `git diff --check`는 오류가 없다.
- Phase 2 `645e55c`의 [일반 Tests CI](https://github.com/twbeatles/xteink-crosspoint-websync/actions/runs/38693576454)는 Linux 전체·Windows 계약 두 작업이 성공했다. 이 원격 결과는 해당 commit 기준이며 최종 문서 commit CI나 모든 native 환경 검증을 대신하지 않는다.
- 별도 검토 담당자가 현재 문서·spec·의존성 설명과 코드 계약을 교차 검토했다. native 스케줄러의 빈 소스 실행은 동기화 성공이 아닌 `no_sites`/exit 1로 정정했고, 현재 shell 환경변수의 스케줄러 상속을 가정하지 않도록 테스트 사본·로그 확인 절차를 명시했다. 외부 검증과 서버 설계를 완료 구현과 구분했다.

### 남은 운영 검증과 지원 한계

[별도 검증 절차](AUDIT_VALIDATION.md)는 실기기 overwrite/receipt 의미, cloud 지연·숨김 replica 동기화, native OS 등록/GUI, 외부 scraper·provider·Calibre, 실제 브라우저 흐름을 구체적인 입력·기대 결과로 정리한다. 중앙 서버 설계는 lease만으로 exactly-once를 주장하지 않으며 firmware/gateway fencing과 idempotent commit·receipt가 필요함을 명시한다. 이 운영·설계 범위는 사용자 승인에 부합하며 이번 로컬 코드 완료의 누락 버그 목록이 아니다.
