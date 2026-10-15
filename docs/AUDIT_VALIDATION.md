# Audit validation and delivery coordination design

2026-10-15. 이 문서는 현재 구현의 검증 절차와 승인된 서버 확장의 설계다. 중앙 서버·새 firmware API를 구현하거나 존재한다고 주장하지 않는다. 실제 기기·외부 서비스·native OS 검사는 아래 절차를 실행한 뒤에만 통과로 기록한다.

## 안전한 검증 경계

아래 외부 검증은 **사용자가 선택하여 실행하는 opt-in 절차**다. 일회용 OS 계정/VM과 테스트용 reader·서재·클라우드 폴더를 사용한다. 기존 앱·스케줄·Watch는 먼저 정지한다. 앱 import 전에 `X3_WEBSYNC_STORAGE_ROOT`를 새 임시 절대 경로로 지정하고 output·watch·backup 경로도 모두 그 안에 둔다. 실제 config/DB·키·기존 기기 파일을 복사할 필요가 없다. 기기 변경 검사는 빈 테스트 폴더에서만 하며 정리할 때도 테스트 중 만든 정확한 파일만 사용자가 확인하여 제거한다.

PowerShell 예시(기기 연결이나 업로드를 하지 않는 로컬 검증):

```powershell
$auditState = Join-Path ([System.IO.Path]::GetTempPath()) ('websync-audit-' + [guid]::NewGuid())
$env:X3_WEBSYNC_STORAGE_ROOT = $auditState
python x3_websync.py --smoke
python -m pytest tests/ -q --tb=short
python scripts/verify_isolated_build.py
```

마지막 명령은 기존 build 의존성이 있는 환경에서만 실행한다. 임시 source/work/dist/state를 만들고 실제 frozen `--smoke`를 실행하며 사용자 dist를 덮어쓰지 않는다. 테스트는 자체 임시 저장소 guard도 사용한다. POSIX에서는 `export X3_WEBSYNC_STORAGE_ROOT="$(mktemp -d)"`를 import 전 설정한다. 감사에서는 dependency 설치를 하지 않는다. 이 환경변수는 OS sandbox가 아니므로 native 명령은 일회용 계정에서만 검사한다.

## 로컬 복구·전송 회귀

1. 테스트 GUI에서 정상 사이트 두 개를 만들고 종료한 뒤 임시 config와 `.bak`의 bytes·revision을 기록한다. 별도 import JSON에 정상 사이트와 `name:null` 사이트를 섞어 가져온다. 전체 거부·원본 bytes/revision 불변·다시 기동 성공을 확인한다. `test_config_input_recovery.py`가 자동 검증한다.
2. 임시 config만 잘못된 구조로 바꾸고 GUI를 기동한다. 취소 시 불변, `.bak` 선택 시 정상 기동·`.rejected.<id>.json` 원본 보존·`.bak` 보존을 확인한다. 동일 절차를 `python x3_websync.py --recover-config <정상 전체 config JSON>`으로 수행한다. 잘못된 복구 파일이면 변경 없이 exit 1, 정상 복구면 exit 0이어야 한다. `--sync`에는 대화상자가 없어야 한다.
3. 같은 표시 이름·다른 feed URL을 등록해 loopback fixture로 합본/선택/EPUB-only를 생성한다. ZIP 두 본문·TOC, 성공 대상의 SQLite URL 둘, 재실행 no_new를 검사한다. 기기 A/B의 선행 이력을 서로 다르게 하고 한 대상 실패 뒤 재시도에서 이미 성공한 기사/대상 조합이 빠지는지 검사한다. `test_pipeline_http_integration.py`에 연결된 경로다.
4. Watch에서 테스트 파일 하나를 추가하고 loopback 업로드를 처음 실패시킨 뒤 새 이벤트 없이 성공시킨다. 재시도 간격은 2, 4, 8…최대 300초이며 한 경로는 중복 큐잉되지 않아야 한다. A 성공/B 실패 뒤 재시작은 B만 전송한다. 같은 크기·mtime로 내용을 바꾸면 모든 대상이 새 내용 대상이다. 폴더/대상 변경, 누락 파일 복귀, 안정화 중 중지, backoff 중 중지, HTTP 진행 중 중지를 각각 검사한다. `test_watch_retry.py`는 이 계약을 짧은 주입 interval로 검사한다.

## 실제 X3/X4 및 API 완료·덮어쓰기 의미

이 검사는 테스트용 reader에만 수행한다. firmware 버전·모델·File Transfer 모드·테스트 폴더를 기록하고 그 폴더가 비어 있는지 확인한다. 기존 `/upload`, 파일 목록·다운로드 등 앱이 실제 사용하는 API만 사용하며 firmware마다 지원 차이를 결과에 적는다.

1. 본문이 다른 유효 EPUB `가.epub`, `ga.epub`을 만들어 파일 탭에서 한 배치로 올린다. 두 전송명과 다운로드한 bytes/SHA-256이 서로 다르고 원본과 일치해야 한다. 악센트/ASCII 쌍, 같은 날짜 합본 두 번도 검사한다. 이름·확장자·날짜가 기기 파일 목록과 일치하는지 기록한다.
2. **덮어쓰기 검사는 사전에 생성한 테스트 파일 하나에만 한정한다.** 같은 basename의 EPUB 내용만 바꿔 다시 올린다. 응답 status/body와 다운로드 bytes를 기록하여 거절/대체/별도 저장 중 어느 동작인지 판정한다. HTTP 200만으로 저장 durability·hash 검증을 추정하지 않는다. 사용자 책에 이 실험을 적용하지 않는다.
3. EPUB을 열어 한국어 제목·본문·TOC·PNG/JPEG/GIF offline 이미지를 확인한다. 이전 앱의 비ASCII 전송명은 자동 정리하지 않으므로 테스트 폴더 내 옛 이름과 새 이름이 공존하는지도 확인한다.
4. 응답 유실은 우선 loopback proxy에서만 재현한다. 업로드 완료 후 응답 폐기, 응답 수신 후 SQLite commit 전 실패를 주입한다. 현행 앱은 실패/불확실 상태를 유지하며 재시도할 수 있어야 한다. 실기기 테스트에서 임의 전원 차단·사용자 데이터 손상을 유발하지 않는다. 실제 원격 receipt가 없으면 정확히 한 번 완료로 판정할 수 없다.

## 클라우드 복제 지연

테스트용 공유 폴더 두 복제본과 두 개의 독립 임시 저장소를 사용한다. 실제 클라우드 client 검사는 개인 공유 폴더와 분리한다. 같은 reader를 향한 자동 전송은 한 PC만 켠다.

1. PC A/B가 offline 상태에서 서로 다른 소스를 추가·편집하고 A는 이력 삭제 표식을 만든다. `.websync-replicas`를 포함해 동기화를 재개한다. canonical 게시 순서를 바꿔도 두 변경과 최신 삭제 표식이 양쪽에 수렴해야 한다.
2. 테스트 snapshot 하나를 잘린 JSON으로 바꾼다. pull 실패 전후 임시 config/DB bytes 또는 논리 레코드를 비교해 오염되지 않아야 한다. 복구한 유효 snapshot으로 수렴을 재확인한다.
3. 숨김 폴더 누락·충돌 사본 생성·동기화 지연을 기록한다. `test_cloud_replica_recovery.py`, `test_backup_interleavings.py`는 합성 복제 순서를 검증하지만 실제 client의 배제 규칙·동기화 완료를 보증하지 않는다.

## Native Windows / Linux / macOS

일회용 VM/계정에서 공백·한글이 있는 설치 경로와 임시 저장소로 수행한다. 실제 사용 계정의 schtasks/crontab/launchd를 바꾸지 않는다. 소스/EXE도 사용자 데이터가 없는 별도 테스트 사본을 사용한다. 스케줄러가 현재 shell의 `X3_WEBSYNC_STORAGE_ROOT`를 자동 상속한다고 가정하지 말고 실제 등록된 실행 환경을 확인한다. 환경변수가 없을 때의 기본 저장 위치도 테스트 사본 안이어야 한다. 로그가 기대한 임시 경로에 없으면 통과로 처리하지 않는다.

- Windows: 테스트 GUI에서 일일 작업을 등록하고 Task Scheduler에서 명령·cwd·현재 권한을 확인한다. 빈 사이트 설정으로 수동 실행하면 `no_sites` 결과와 `--sync` exit 1이 예상된다. 해당 임시 저장소 로그로 작업이 올바른 앱/경로를 실행했는지 판정하며 이것을 동기화 성공으로 기록하지 않는다. 성공 경로는 loopback 소스·fake reader를 별도로 연결해 exit 0와 이력을 확인한다. 등록 해제 뒤 테스트 작업만 사라져야 한다. frozen `--smoke`도 수행한다.
- Linux/macOS: 등록 전후 `crontab -l` 또는 해당 launchd job 목록을 저장한다. GUI 등록→빈 소스 실행→해제를 수행하고 기존 항목이 보존되었는지 비교한다. 빈 소스는 scrape/upload 없이 `no_sites`와 exit 1이 예상되며 로그로 올바른 실행을 확인한다. 성공 경로는 별도의 loopback 소스·fake reader로 exit 0와 이력을 확인한다. cron/launchd의 제한된 PATH·UTF-8 경로·로그 위치·알림 권한을 확인한다.
- 세 OS GUI: 느린 loopback 전송, pending Watch, 서버 요청 중 창을 닫는다. UI 이벤트 처리가 유지되고 새 작업이 거부되며 자기 worker·commit·백업 flush 이후 종료되어야 한다. 재기동 시 락 해제·미완료 Watch 복구를 확인한다. forced kill의 exactly-once 보장은 없다.

## 외부 scraper 및 provider

기존 `scripts/validate_korean_scrapers.py`를 사용한다. 테스트 임시 저장소 환경에서 먼저 `--only rss,naver,tistory --delay 2 --json <임시 절대경로>` 등 필요한 공개 샘플만 요청한다. optional 샘플은 `--include-optional`을 명시한다. 결과 status·URL·본문 길이·오류를 저장한다. 사이트 접근 제한을 우회하지 않는다. 스크립트는 수집 검증이며 기기 업로드·DB 완료 기록을 하지 않는다. 종료된 Naver Post의 명확한 실패는 서비스 복구 버그로 분류하지 않는다.

실제 Calibre는 테스트 서재에서 list→우선 포맷 경로→Watch 복사 완료를 확인한다. 번역/요약은 사용자가 제공한 테스트 계정·키로 짧은 비민감 기사 하나를 처리하고 HTML 구조·본문 언어·실패 fallback·timeout·취소를 확인한다. 키/본문을 결과물에 넣지 않는다. `googletrans>=4.0.2,<5` adapter의 async 계약은 `test_translator.py`, `test_googletrans_contract.py`의 mock/fake transport 검증과 별개로 실제 서비스 가용성이 필요하다.

## 브라우저 dashboard

임시 서비스는 loopback에만 bind하고 테스트 토큰·synthetic 동기화 callback을 사용한다. 원본 설정·실제 reader·외부 scrape에 연결하지 않는다. 기존 HTTP/template 계약 테스트를 먼저 실행한다.

브라우저에서 login→dashboard→sync→5초 status/log polling→busy 상태에서 다시 sync→cancel→완료 뒤 버튼 재활성화를 확인한다. 잘못된 토큰은 401, 실행 중 재시작은 409, 취소는 현재 작업만 대상으로 해야 한다. proxy로 mutation 응답 하나를 폐기하면 안내가 표시되고 mutation이 자동 재전송되지 않아야 한다. 브라우저 console error·네트워크 요청 수·callback 횟수·최종 상태를 기록한다. 원격 CI/실제 브라우저를 실행하지 않았다면 HTTP 계약 통과만으로 브라우저 E2E 통과라고 적지 않는다.

## 향후 중앙 조정 서버 설계 — 구현 범위 밖

사용자 승인 범위는 설계와 검증 절차다. 아래 저장 필드/프로토콜은 제안이며 현재 CrossPoint API가 아니다.

### 식별성과 상태

reader의 stable device ID와 별도로 `artifact_id = SHA256(최종 EPUB bytes)`를 사용하고, delivery key는 `(device_id, normalized_remote_dir, artifact_id)`로 잡는다. 같은 기사라도 빌드 timestamp·변환 결과가 다르면 bytes가 바뀔 수 있으므로 스케줄 job ID·기사 집합/변환 설정 manifest·최종 artifact를 서버에 한 번 고정해 클라이언트 간 공유한다. 로컬 basename hash는 사람용 전송명 구별이며 idempotency key가 아니다. config/주소 변경과 기기 교체를 구분하는 관리 절차도 필요하다.

서버 DB에는 unique delivery key, 상태(pending/leased/uncertain/committed), owner installation ID, lease deadline, monotonic fencing token, revision, artifact hash/size, durable receipt를 둔다. 상태 변경은 transaction과 revision CAS로 한다. 시간 판단은 서버 clock을 사용하며 lease 갱신·재획득은 token을 증가시킨다. offline client는 lease 없이 새 자동 전송을 시작하지 않는다. 가용성보다 중복 억제를 택하는 명시적 운영 정책이다.

### Lease, fencing, outbox

1. 클라이언트는 content-addressed artifact와 manifest를 준비하고 DB outbox에 intent를 transaction으로 저장한다. 서버는 한 delivery key의 lease를 CAS로 수락하고 token을 발급한다.
2. worker는 lease 유효성을 확인하며 전송한다. outbox는 성공 응답/receipt를 durable하게 기록한 뒤 기사 이력 변경과 같은 transaction으로 commit한다. 재실행은 outbox를 읽어 복구하고 모호한 결과를 성공으로 추정하지 않는다.
3. lease 만료만으로 오래된 worker가 멈추지는 않는다. firmware 또는 모든 업로드가 통과하는 gateway가 token을 검사해 이전 token의 write/commit을 거부해야 fencing이 효과가 있다. 클라이언트만 검사하면 네트워크 지연 후 옛 요청이 도착하는 race가 남는다.
4. `artifact_id`로 재요청해도 같은 receipt를 반환하는 기기 측 idempotent commit, 임시 업로드→hash 검증→원자 게시, receipt 조회가 있어야 한다. receipt는 device ID·artifact ID·폴더·hash·완료 token에 결합한다. 단순 파일 존재/길이만으로 내용·원자성·완료를 확인하지 않는다.
5. 기기가 지원하지 않으면 gateway/server lease는 동시 전송 확률을 낮추지만, 기기 저장 후 HTTP 응답 유실 또는 HTTP 성공 후 로컬/서버 commit 전 종료를 원자화하지 못한다. 이 경우 상태는 uncertain으로 남기고 검증/운영자 선택 후 재전송한다. 현행 앱은 best-effort 재시도이며 true exactly-once를 주장하지 않는다.

### 설계 수락 검증

가상 firmware와 두 client를 사용해 같은 key 동시 획득은 한 owner만 수락되는지 검사한다. lease 만료·옛 요청 지연 도착·clock skew·서버 재시작·partition·outbox replay를 주입한다. 옛 fencing token은 기기/gateway에서 거부되어야 하고 새 token 재전송은 동일 receipt와 단 하나의 게시 artifact를 반환해야 한다. upload 완료 직전/직후, receipt 응답 전/후, 이력 commit 전/후 각 지점에서 worker를 종료하여 재기동 시 committed 또는 검증 가능한 uncertain으로만 수렴하는지 확인한다. 서버 DB 복구·unique 제약·CAS 실패·receipt 위변조도 검사한다. 실제 firmware의 idempotent commit/receipt 지원을 실증하기 전에는 이 설계의 정확히 한 번 보장을 출시 조건으로 충족했다고 판정하지 않는다.
