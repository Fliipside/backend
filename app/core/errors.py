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
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"AI service returned HTTP {status_code}")

class AIServiceBadResponseError(AIServiceError):
    """Raised when the AI service returns an invalid response."""

