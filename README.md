# Flipside backend

모바일 앱과 웹이 사용하는 FastAPI 서버입니다. 이 저장소는 HTTP API, 인증, 데이터 접근, 파일 처리, AI 서비스 연동을 담당합니다. AI 모델 학습과 추론 구현은 별도 폴더 또는 서비스에서 관리합니다.

## 코드 경계

```text
app/
├── main.py             # 앱 생성, 연결 수명주기, 상태 확인
├── api/
│   ├── deps.py         # 요청에서 공통 연결을 꺼내는 의존성
│   └── v1/             # 버전별 HTTP 라우터
├── schemas/            # 요청과 응답의 데이터 계약
├── services/           # 기능별 서버 워크플로 조합
├── repositories/       # PostgreSQL 조회 및 저장
├── clients/            # 외부 AI 서비스, 오브젝트 스토리지, Redis 작업 큐
├── workers/            # 별도 프로세스로 실행하는 비동기 작업 워커
├── db/                 # SQLAlchemy 기반 및 세션
└── core/               # 환경 설정, 공통 오류, 인증 보안
```

라우터는 HTTP 입력·출력을 처리하고, 서비스는 DB·Redis·외부 AI 호출을 조합합니다. SQL 쿼리는 `repositories/`에 둡니다. PostgreSQL이 원본 서비스 데이터의 저장소이며, 관계 분석의 임베딩과 유사도 검색은 **같은 PostgreSQL의 pgvector 확장**을 사용합니다. 벡터 차원, 테이블, 인덱스, 마이그레이션은 실제 임베딩 모델과 데이터 요구사항이 정해지면 추가합니다.

`app/main.py`는 설정된 PostgreSQL 연결 풀, Redis 클라이언트, 외부 AI HTTP 클라이언트, 오브젝트 스토리지 클라이언트를 앱 시작 시 만들고 종료 시 닫습니다. 설정이 없는 연결은 만들지 않으므로 로컬에서 API 골격을 단독 실행할 수 있습니다.

## 음성 분석 비동기 처리

음성 분석은 몇 분이 걸리므로 API가 바로 처리하지 않고 워커에 넘깁니다.

```text
앱 → POST /api/v1/voice/analyses  (file, customer_id, kind, title, occurred_at)
       폼 값과 고객 확인 → 녹음을 OCI Object Storage(S3 호환)에 저장
       → interactions 행과 voice_analysis_jobs 행(queued)을 한 트랜잭션으로 생성
       → Redis 큐에 job_id 등록 → 202 (job_id, interaction_id)
워커 → 큐에서 job_id를 꺼냄(processing) → 녹음 다운로드 → ai POST voice/analyze 호출
       → 성공: succeeded + result 저장 / 실패: failed + error_code / 일시 오류: 지연 후 재시도
앱 → GET /api/v1/voice/analyses/{job_id}  (본인 작업만 조회)
```

- **작업 상태와 결과**는 PostgreSQL `voice_analysis_jobs` 테이블이 원본입니다. Redis에는 job_id만 들어갑니다.
- **대화(`interactions`)**: 녹음 1건은 고객 1명과의 대화 1건입니다. `voice_analysis_jobs`는 처리 상태만 담고, 어떤 고객과의 어떤 대화인지는 `interactions` 테이블(`id` UUID, `customer_id`, `owner_user_id`, `kind`, `title`, `occurred_at`)에 둡니다. 작업은 `voice_analysis_jobs.interaction_id`로 대화를 가리킵니다. 이 테이블이 생기기 전에 만든 작업은 `interaction_id`가 `NULL`이고, 조회 응답의 `interaction_id`, `customer_id`, `kind`, `title`, `occurred_at`도 `null`입니다.
- **업로드 폼 값**: `file` 외에 아래 값을 multipart form 필드로 받습니다. 선택 항목은 빼거나 빈 값으로 보내면 기본값을 씁니다.

  | 필드 | 필수 | 기본값 | 설명 |
  | --- | --- | --- | --- |
  | `customer_id` | 필수 | 없음 | 본인이 등록한 고객의 id(정수) |
  | `kind` | 선택 | `meeting` | `meeting`(대면 미팅) 또는 `call`(통화) |
  | `title` | 선택 | 업로드 파일명에서 확장자를 뺀 것 | 200자까지. 앞뒤 공백은 뗍니다 |
  | `occurred_at` | 선택 | 업로드 시각 | 대화가 있었던 시각. ISO 8601이고 시간대가 있어야 합니다. 예: `2026-11-20T14:00:00+09:00`, `2026-11-20T05:00:00Z`. UTC로 바꿔 저장합니다 |

- **⚠️ 기존 요청과 호환되지 않음**: `customer_id`가 필수라서 `file`만 보내던 기존 요청은 `400 INVALID_REQUEST`가 됩니다. 프런트는 나중에 맞추기로 한 의도한 동작입니다.
- **업로드 검증**: 폼 값과 고객은 녹음을 저장소에 올리기 전에 확인하므로, 거절된 요청은 파일도 행도 남기지 않습니다. 폼 값이 틀리면(`customer_id` 없음·정수 아님, `kind`가 다른 값, `title` 200자 초과, `occurred_at` 형식 오류·시간대 없음) `400 INVALID_REQUEST`이고 `message`에 어느 값이 틀렸는지 나옵니다. 없는 고객 id와 다른 사용자의 고객 id는 똑같이 `404 CUSTOMER_NOT_FOUND`입니다.
- **삭제**: 고객을 삭제하면 그 고객의 대화도 함께 삭제되고, 작업 행은 남되 `interaction_id`가 `NULL`이 됩니다.
- **ai로 보내는 값**: 워커가 ai `voice/analyze`로 보내는 값(`file`, `voiceprint`)은 그대로입니다. 대화 정보는 보내지 않습니다.
- **Redis 키** (`flipside:voice-analysis:*`): `pending`(대기 목록), `processing`(처리 중), `delayed`(재시도 대기, sorted set). 처리가 끝나면 키에서 빠지므로 만료(TTL)를 두지 않습니다. 워커는 시작할 때 `processing`에 남은 작업을 되돌리고, DB에서 끝나지 않은 작업 중 Redis에 없는 작업을 다시 넣습니다.
- **재시도**: ai 429, 502, 503(`*_NOT_CONFIGURED` 제외), 504, 연결 실패, 저장소 오류. 최대 `VOICE_ANALYSIS_MAX_ATTEMPTS`회, 간격은 ai가 준 `Retry-After`(초)를 우선하고 없으면 `VOICE_ANALYSIS_RETRY_BASE_SECONDS × 2^(시도-1)`입니다. ai 호출 timeout은 재시도하지 않습니다.
- **분석 중 거절**: ai는 분석을 한 번에 하나만 합니다. 다른 분석 중이라 `503 VOICE_BUSY`로 거절하면(예: 워커 재시작 직후 같은 작업을 다시 보낸 경우) 시도 횟수에 넣지 않고 `Retry-After`(보통 60초) 뒤에 다시 보냅니다. 첫 처리 시작부터 `VOICE_ANALYSIS_BUSY_MAX_WAIT_SECONDS`(기본 3600초)가 지나도 계속 거절되면 `VOICE_BUSY`로 실패 처리합니다.
- **녹음 길이**: 길이 제한은 ai가 판단합니다. 60분을 넘는 녹음은 ai가 `400 AUDIO_TOO_LONG`으로 거절하고, 재시도 없이 "녹음이 60분을 넘어 분석할 수 없습니다."로 실패 처리합니다.
- **화자 이름**: ai가 정한 이름을 그대로 저장합니다. "나"는 `me`, 나머지는 처음 말한 순서대로 `A`, `B`, `C`…(26명 넘으면 `AA`, `AB`…)입니다. 목소리 미등록 등으로 "나"를 찾지 못하면 모두 `A`부터 붙고 role은 `unknown`입니다.
- **파일 크기**: 녹음은 `VOICE_RECORDING_MAX_BYTES`(기본 1GB)까지 받습니다. 길이 제한은 ai가 하므로 이 값은 서버 보호용 상한입니다. 60분 기준 m4a는 약 60MB, 44.1kHz 스테레오 WAV는 약 635MB, 48kHz 24bit 스테레오는 약 1GB입니다. API 앞단에 프록시(nginx 등)가 있으면 업로드 크기 제한(`client_max_body_size` 등)도 같은 값으로 맞춰야 합니다. 업로드 파일은 API 서버의 임시 디스크와 워커의 임시 파일에 한 번씩 저장되므로 서버 디스크 여유도 필요합니다.
- **녹음 원본**은 `voice-recordings/{user_id}/{job_id}.{확장자}`에 저장하고 분석 후에도 보관합니다.
- **timeout**: 분석은 `AI_ANALYZE_TIMEOUT_SECONDS`(기본 1800), 목소리 등록은 `AI_ENROLL_TIMEOUT_SECONDS`(기본 120)를 씁니다. 다른 AI 호출은 `AI_SERVICE_TIMEOUT_SECONDS`(30)를 그대로 씁니다.
- **목소리 등록**(`POST /api/v1/voice/enroll`)은 동기 호출입니다. ai가 돌려준 `engine`과 256차원 `vector`를 `voiceprints` 테이블에 사용자당 하나 저장하고(JSONB. 벡터 비교는 ai가 하므로 pgvector를 쓰지 않음), 분석할 때 `voiceprint` form 필드로 함께 보냅니다.

워커 실행 (동시 실행 수 1, 컨테이너도 하나만 띄웁니다):

```bash
python -m app.workers.voice_analysis
```

## 이미지 업로드

명함 사진처럼 사용자가 올리는 이미지를 저장합니다. 이미지는 특정 화면에 묶이지 않은 독립 리소스이고, 앱은 돌려받은 `image_id`를 자기 데이터(예: 고객)에 저장해 둡니다.

```text
앱 → POST /api/v1/images (multipart file)
       크기·형식 확인 → OCI Object Storage 저장 → images 행 생성 → 201 (image_id, url)
앱 → GET /api/v1/images/{image_id}     (본인 것만) → 새 서명 URL
앱 → DELETE /api/v1/images/{image_id}  (본인 것만) → 저장소 파일 삭제 후 행 삭제
```

- **형식**: JPEG, PNG, WebP만 받습니다. 요청의 Content-Type이 아니라 파일 앞부분 바이트로 판별하고, 판별한 형식을 저장합니다. 그 외는 `415 INVALID_IMAGE`입니다. 서버는 크기를 줄이거나 형식을 바꾸지 않으므로, HEIC 같은 형식은 앱이 JPEG로 바꿔서 보내야 합니다.
- **크기**: `IMAGE_MAX_BYTES`(기본 10MB)까지 받습니다. 넘으면 `413 PAYLOAD_TOO_LARGE`입니다. 요청 본문이 이 값(+multipart 여유 64KB)을 넘으면 로그인 확인이나 파일 저장보다 먼저 거절하므로, 크기가 큰 요청은 토큰이 없어도 `401`이 아니라 `413`을 받습니다. `Content-Length`가 없는 chunked 요청도 받은 바이트를 세어 같은 기준으로 끊습니다.
- **보기**: 버킷은 비공개입니다. 응답의 `url`은 `IMAGE_URL_EXPIRE_SECONDS`(기본 3600초) 동안만 열리는 서명 URL이라 토큰 없이 `<img src>`에 바로 쓸 수 있습니다. `url_expires_at`이 지나면 `GET`으로 다시 받습니다. URL을 아는 사람은 만료 전까지 볼 수 있으므로 오래 저장하거나 공유하지 않습니다.
- **저장 위치**: `images/{user_id}/{image_id}.{jpg|png|webp}`
- **바꾸기**: ① 새 이미지를 올리고 ② 새 `image_id`를 앱 데이터(예: 고객)에 저장한 뒤 ③ 저장이 성공하면 이전 `image_id`를 삭제합니다. 이전 이미지를 먼저 지우면 ②가 실패했을 때 앱 데이터가 이미 지워진 이미지를 가리키게 됩니다.
- **삭제 순서**: 저장소 파일을 먼저 지우고 행을 지웁니다. 저장소 오류면 `503`을 돌려주고 행이 남으므로 다시 시도할 수 있습니다.

## 고객

고객 1건은 사용자가 만나는 상대 회사의 담당자 1명입니다. 화면에는 "노바테크 / IT·솔루션 · 김민준 사업개발팀 부장"처럼 나옵니다. 녹음 업로드가 받을 `customer_id`가 이 테이블의 `id`를 가리킵니다.

```text
앱 → POST  /api/v1/customers                → customers 행 생성 → 201 (customer_id)
앱 → GET   /api/v1/customers                → 본인이 등록한 고객 전체, 최근 등록 순
앱 → GET   /api/v1/customers/{customer_id}  (본인 것만)
앱 → PATCH /api/v1/customers/{customer_id}  (본인 것만) → 보낸 항목만 수정
```

- **id**: 사용자 id는 UUID지만 고객 id(`customer_id`)는 자동 증가 정수입니다.
- **항목**: `company_name`(필수, 100자), `industry`(100자), `name`(필수, 50자), `department`(100자), `title`(50자). 앞뒤 공백은 떼고 저장합니다. 선택 항목은 빼거나 `null`, 빈 문자열로 보내면 `null`로 저장합니다.
- **수정**: 본문에 넣은 항목만 바뀝니다. 선택 항목은 `null`이나 빈 문자열을 보내 비울 수 있고, 필수 항목에 `null`이나 빈 값을 보내면 `422`입니다.
- **소유자**: 로그인한 사용자가 등록한 고객만 다룹니다. 없는 id와 다른 사용자의 고객 id는 똑같이 `404 CUSTOMER_NOT_FOUND`입니다. 사용자를 삭제하면 그 사용자의 고객도 함께 삭제됩니다.
- **목록**: 한 번에 전부 돌려줍니다. 검색, 페이지 나누기, 삭제 API는 아직 없습니다.

## 로컬 실행

Python **3.11.x**에서 `backend` 디렉터리로 이동한 뒤:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

`.env.example`을 참고해 `.env`를 만듭니다. 인증 API를 쓰려면 PostgreSQL 설정과 32바이트 이상의 무작위 `JWT_SECRET_KEY`가 필요합니다. 예를 들어 `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성할 수 있습니다. 테이블은 `alembic upgrade head`로 생성합니다.

이메일을 보내려면 `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`을 모두 채웁니다. 일부만 채우면 서버가 시작되지 않고, 모두 비우면 이메일 기능만 꺼집니다. Gmail은 `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`로 두고 `SMTP_PASSWORD`에 계정 비밀번호가 아닌 앱 비밀번호(16자리, 띄어쓰기 없이)를 넣습니다. 포트 465는 처음부터 TLS로, 그 외 포트는 STARTTLS로 접속합니다.

회원가입 이메일 인증과 비밀번호 재설정은 SMTP와 Redis, PostgreSQL이 모두 연결돼 있어야 동작합니다.

- 인증번호는 6자리 숫자이며 Redis에 해시로만 저장합니다. `EMAIL_CODE_EXPIRE_SECONDS`(기본 600초) 뒤 만료되고, `EMAIL_CODE_MAX_ATTEMPTS`(기본 5회)를 넘게 틀리면 폐기됩니다.
- 같은 주소로는 `EMAIL_CODE_RESEND_COOLDOWN_SECONDS`(기본 60초)에 한 번, 하루 `EMAIL_RECIPIENT_DAILY_LIMIT`(기본 10회)까지 요청할 수 있습니다.
- 서비스 전체로는 하루(UTC 기준) `EMAIL_DAILY_SEND_LIMIT`(기본 250통)까지만 보냅니다. Gmail 한도가 최근 24시간 기준 500명이라, 날짜가 바뀌는 시점에 걸쳐도 넘지 않도록 절반으로 잡았습니다.
- 메일은 응답을 보낸 뒤에 발송하고, 결과를 `email_logs` 테이블에 `pending` → `sent` 또는 `failed`로 남깁니다. `sent`는 SMTP 서버가 접수했다는 뜻이며 수신함 도착을 보장하지 않습니다.
- 비밀번호 재설정 요청은 가입 여부와 관계없이 같은 응답을 줍니다. 비밀번호를 바꿔도 이미 발급된 access token은 만료 시각까지 유효합니다.

## 현재 API 상태

| 경로                              | 설명                                  |
| --------------------------------- | ------------------------------------- |
| `GET /health`                     | 서버 프로세스 생존 확인 (DB·Redis 상태는 확인하지 않음) |
| `POST /api/v1/auth/email-verification/request` | 회원가입용 인증번호 메일 발송 (`email`) |
| `POST /api/v1/auth/email-verification/confirm` | 인증번호 확인 (`email`, `code`), 성공 후 30분 안에 가입 |
| `POST /api/v1/auth/signup`        | 회원가입 (`email`, `password`, `nickname`, `company`), 이메일 인증을 마친 주소만 가능. 비밀번호는 영문과 숫자를 포함한 8자 이상 |
| `POST /api/v1/auth/password-reset/request` | 비밀번호 재설정 인증번호 메일 발송 (`email`) |
| `POST /api/v1/auth/password-reset/confirm` | 인증번호 확인 후 비밀번호 변경 (`email`, `code`, `new_password`). 새 비밀번호도 같은 규칙 |
| `POST /api/v1/auth/login`         | 로그인, access token 발급             |
| `GET /api/v1/auth/me`             | 내 정보 조회 (`Authorization: Bearer <token>`) |
| `POST /api/v1/emotion/infer`      | 외부 AI 서비스로 감정 분석 요청       |
| `POST /api/v1/voice/enroll`       | 목소리 등록 (multipart `file`, 인증 필요) |
| `POST /api/v1/voice/analyses`     | 음성 분석 작업 등록, 202 (multipart `file`, `customer_id` 필수, `kind`·`title`·`occurred_at` 선택, 인증 필요) |
| `GET /api/v1/voice/analyses/{job_id}` | 음성 분석 상태·결과와 대화 정보 조회 (본인 작업만) |
| `POST /api/v1/images`             | 이미지 업로드, 201 (multipart `file`, 인증 필요) |
| `GET /api/v1/images/{image_id}`   | 이미지 정보와 서명 URL 조회 (본인 것만) |
| `DELETE /api/v1/images/{image_id}` | 이미지 삭제 (본인 것만)              |
| `POST /api/v1/customers`          | 고객 등록, 201 (`company_name`, `name` 필수, 인증 필요) |
| `GET /api/v1/customers`           | 내가 등록한 고객 목록, 최근 등록 순   |
| `GET /api/v1/customers/{customer_id}` | 고객 단건 조회 (본인 것만)        |
| `PATCH /api/v1/customers/{customer_id}` | 고객 수정, 보낸 항목만 (본인 것만) |
| `POST /api/v1/relationship/infer` | 미구현 (501)                          |

인증이 필요한 API는 `app/api/deps.py`의 `get_current_user` 의존성을 사용합니다.

## Docker

```powershell
docker build -t flipside-backend .
docker run --rm -p 8000:8000 flipside-backend
```

운영 환경에서는 연결 설정을 환경 변수나 비밀 관리 서비스로 주입합니다.

워커는 같은 이미지를 command만 바꿔 별도 컨테이너로 실행합니다. 서버의 compose 파일에 `backend-worker` 서비스가 있어야 CI 배포가 성공합니다.

```yaml
  backend-worker:
    image: yjs0120/spring-boot-app:flipside-backend
    container_name: flipside-backend-worker
    command: ["python", "-m", "app.workers.voice_analysis"]
    restart: unless-stopped
```

이미지에 `.env`가 들어 있으므로 워커도 API와 같은 설정을 씁니다. `depends_on` 등은 서버 compose의 서비스 이름에 맞춰 추가합니다.
