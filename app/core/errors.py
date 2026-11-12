class AppError(Exception):

    def __init__(
            self,
            *,
            status_code: int,
            code: str,
            message: str,
            headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        super().__init__(message)

class FeatureNotReadyError(AppError):

    def __init__(self, feature: str) -> None:
        super().__init__(
                status_code=501,
                code="FEATURE_NOT_READY",
                message=f"{feature} API workflow is not implemented yet",
            )

class AuthenticationError(AppError):

    def __init__(self, message: str = "인증이 필요합니다.") -> None:
        super().__init__(
                status_code=401,
                code="UNAUTHORIZED",
                message=message,
                headers={"WWW-Authenticate": "Bearer"},
            )

class InvalidCredentialsError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="이메일 또는 비밀번호가 올바르지 않습니다.",
            )

class InactiveUserError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=403,
                code="INACTIVE_USER",
                message="비활성화된 사용자입니다.",
            )

class EmailAlreadyExistsError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=409,
                code="EMAIL_ALREADY_EXISTS",
                message="이미 사용 중인 이메일입니다.",
            )

class AuthNotConfiguredError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=503,
                code="SERVICE_UNAVAILABLE",
                message="Authentication is not configured",
            )

class AIServiceError(Exception):
    """Base error for communication with the external AI service."""

class AIServiceConnectionError(AIServiceError):
    """Raised when the AI service cannot be reached."""

class AIServiceTimeoutError(AIServiceError):
    """Raised when the AI service does not respond in time."""

class AIServiceUpstreamError(AIServiceError):
    def __init__(
            self,
            status_code: int,
            code: str | None = None,
            retry_after_seconds: float | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"AI service returned HTTP {status_code} ({code})")

class AIServiceBadResponseError(AIServiceError):
    """Raised when the AI service returns an invalid response."""


class PayloadTooLargeError(AppError):

    def __init__(self, max_bytes: int) -> None:
        super().__init__(
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                message=f"파일 크기는 {max_bytes} 바이트를 넘을 수 없습니다.",
            )

class EmptyFileError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=400,
                code="EMPTY_FILE",
                message="빈 파일은 업로드할 수 없습니다.",
            )

class InvalidAudioError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=400,
                code="INVALID_AUDIO",
                message="음성 파일을 처리할 수 없습니다.",
            )

class VoiceAnalysisNotFoundError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=404,
                code="VOICE_ANALYSIS_NOT_FOUND",
                message="음성 분석 작업을 찾을 수 없습니다.",
            )

class InvalidImageError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=415,
                code="INVALID_IMAGE",
                message="JPG, PNG, WebP 사진만 올릴 수 있습니다.",
            )

class ImageNotFoundError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=404,
                code="IMAGE_NOT_FOUND",
                message="이미지를 찾을 수 없습니다.",
            )

class ServiceNotConfiguredError(AppError):

    def __init__(self, service: str) -> None:
        super().__init__(
                status_code=503,
                code="SERVICE_UNAVAILABLE",
                message=f"{service} is not configured",
            )

class ObjectStorageError(Exception):
    """Raised when the object storage request fails."""

class ObjectNotFoundError(ObjectStorageError):
    """Raised when the requested object does not exist."""

class StorageUnavailableError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=503,
                code="STORAGE_UNAVAILABLE",
                message="파일 저장소에 연결할 수 없습니다.",
            )

class QueueUnavailableError(AppError):

    def __init__(self) -> None:
        super().__init__(
                status_code=503,
                code="QUEUE_UNAVAILABLE",
                message="작업 큐에 연결할 수 없습니다.",
            )
