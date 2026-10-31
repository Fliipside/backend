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
