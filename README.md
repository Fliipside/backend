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
앱 → POST /api/v1/voice/analyses
       녹음을 OCI Object Storage(S3 호환)에 저장 → voice_analysis_jobs 행 생성(queued)
       → Redis 큐에 job_id 등록 → 202
워커 → 큐에서 job_id를 꺼냄(processing) → 녹음 다운로드 → ai POST voice/analyze 호출
       → 성공: succeeded + result 저장 / 실패: failed + error_code / 일시 오류: 지연 후 재시도
앱 → GET /api/v1/voice/analyses/{job_id}  (본인 작업만 조회)
```

- **작업 상태와 결과**는 PostgreSQL `voice_analysis_jobs` 테이블이 원본입니다. Redis에는 job_id만 들어갑니다.
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

## 로컬 실행

Python **3.11.x**에서 `backend` 디렉터리로 이동한 뒤:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

`.env.example`을 참고해 `.env`를 만듭니다. 인증 API를 쓰려면 PostgreSQL 설정과 32바이트 이상의 무작위 `JWT_SECRET_KEY`가 필요합니다. 예를 들어 `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성할 수 있습니다. 테이블은 `alembic upgrade head`로 생성합니다.

## 현재 API 상태

| 경로                              | 설명                                  |
| --------------------------------- | ------------------------------------- |
| `GET /health`                     | 서버 프로세스 생존 확인 (DB·Redis 상태는 확인하지 않음) |
| `POST /api/v1/auth/signup`        | 회원가입 (`email`, `password`, `nickname`) |
| `POST /api/v1/auth/login`         | 로그인, access token 발급             |
| `GET /api/v1/auth/me`             | 내 정보 조회 (`Authorization: Bearer <token>`) |
| `POST /api/v1/emotion/infer`      | 외부 AI 서비스로 감정 분석 요청       |
| `POST /api/v1/voice/enroll`       | 목소리 등록 (multipart `file`, 인증 필요) |
| `POST /api/v1/voice/analyses`     | 음성 분석 작업 등록, 202 (multipart `file`, 인증 필요) |
| `GET /api/v1/voice/analyses/{job_id}` | 음성 분석 상태·결과 조회 (본인 작업만) |
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
