class AppError(Exception):

    def __init__(
            self,
            *,
            status_code: int,
            code: str,
            message: str,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)

class FeatureNotReadyError(AppError):

    def __init__(self, feature: str) -> None:
        super().__init__(
                status_code=501,
                code="FEATURE_NOT_READY",
                message=f"{feature} API workflow is not implemented yet",
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

