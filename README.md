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
├── repositories/       # PostgreSQL 조회 및 저장 (기능 구현 시 추가)
├── db/                 # SQLAlchemy 기반 및 세션
└── core/               # 환경 설정과 공통 오류
```

라우터는 HTTP 입력·출력을 처리하고, 서비스는 DB·Redis·외부 AI 호출을 조합합니다. SQL 쿼리는 `repositories/`에 둡니다. PostgreSQL이 원본 서비스 데이터의 저장소이며, 관계 분석의 임베딩과 유사도 검색은 **같은 PostgreSQL의 pgvector 확장**을 사용합니다. 벡터 차원, 테이블, 인덱스, 마이그레이션은 실제 임베딩 모델과 데이터 요구사항이 정해지면 추가합니다.

`app/main.py`는 설정된 PostgreSQL 연결 풀, Redis 클라이언트, 외부 AI HTTP 클라이언트를 앱 시작 시 만들고 종료 시 닫습니다. 설정이 없는 연결은 만들지 않으므로 로컬에서 API 골격을 단독 실행할 수 있습니다. 오브젝트 스토리지 연동은 업로드 방식과 OCI/S3 호환 설정이 정해지면 서비스 경계에 추가합니다.

## 로컬 실행

Python **3.11.x**에서 `backend` 디렉터리로 이동한 뒤:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

`.env.example`을 참고해 `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`를 설정합니다. 서버는 이 값으로 PostgreSQL 연결 URL을 구성합니다.

## 현재 API 상태

| 경로                              | 임시 입력                                     | 현재 동작                    |
| --------------------------------- | --------------------------------------------- | ---------------------------- |
| `GET /health`                     | 없음                                          | 서버 프로세스 생존 확인, 200 |
| `POST /api/v1/voice/infer`        | `file` 오디오 업로드                          | 501                          |
| `POST /api/v1/emotion/infer`      | `{"text":"..."}`                              | 501                          |
| `POST /api/v1/relationship/infer` | `{"messages":[{"speaker":"A","text":"..."}]}` | 501                          |

`/health`는 DB·Redis 연결 상태를 보증하지 않습니다. 세 `infer` 경로의 입력은 임시 계약이고, 결과를 반환하는 기능은 아직 없습니다. 각 기능을 구현할 때 입력·출력 스키마를 확정하고, 필요한 repository와 외부 서비스 호출을 연결하세요. 인증/JWT, 실제 저장 스키마, pgvector 마이그레이션, 파일 저장 방식도 아직 구현되지 않았습니다.

## Docker

```powershell
docker build -t flipside-backend .
docker run --rm -p 8000:8000 flipside-backend
```

운영 환경에서는 연결 설정을 환경 변수나 비밀 관리 서비스로 주입합니다.
