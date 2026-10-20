from app.core.errors import FeatureNotReadyError
from app.schemas.relationship import RelationshipRequest


async def infer_relationship(request: RelationshipRequest) -> None:
    # Combine PostgreSQL/pgvector retrieval with the separate AI service here.
    raise FeatureNotReadyError("relationship")
