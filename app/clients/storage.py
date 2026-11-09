import asyncio
from typing import Any, BinaryIO, Protocol

from app.core.config import Settings
from app.core.errors import ObjectNotFoundError, ObjectStorageError


class ObjectStorage(Protocol):
    async def upload(
            self,
            key: str,
            content: BinaryIO,
            content_type: str | None,
    ) -> None: ...

    async def download(self, key: str, destination: BinaryIO) -> None: ...


class S3ObjectStorage:
    """OCI Object Storage via its S3-compatible API. boto3 is sync, so calls run in threads."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStorage":
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            # OCI requires path-style addressing.
            config=Config(s3={"addressing_style": "path"}),
        )
        return cls(client, settings.s3_bucket)

    async def upload(
            self,
            key: str,
            content: BinaryIO,
            content_type: str | None,
    ) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        await self._call(
            self._client.upload_fileobj,
            content,
            self._bucket,
            key,
            ExtraArgs=extra_args,
        )

    async def download(self, key: str, destination: BinaryIO) -> None:
        await self._call(
            self._client.download_fileobj,
            self._bucket,
            key,
            destination,
        )

    async def _call(self, func: Any, *args: Any, **kwargs: Any) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            await asyncio.to_thread(func, *args, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError from exc
            raise ObjectStorageError from exc
        except BotoCoreError as exc:
            raise ObjectStorageError from exc
