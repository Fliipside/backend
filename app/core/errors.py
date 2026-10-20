class FeatureNotReadyError(Exception):
    """Raised until a feature's server-side workflow is connected."""

    def __init__(self, feature: str) -> None:
        super().__init__(f"{feature} API workflow is not implemented yet")
