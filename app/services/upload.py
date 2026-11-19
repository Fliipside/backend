import asyncio
from typing import BinaryIO

from fastapi import UploadFile

from app.core.errors import EmptyFileError, PayloadTooLargeError


async def measure_upload(file: UploadFile, max_bytes: int) -> int:
    def measure(content: BinaryIO) -> int:
        content.seek(0, 2)
        size = content.tell()
        content.seek(0)
        return size

    size = await asyncio.to_thread(measure, file.file)
    if size == 0:
        raise EmptyFileError
    if size > max_bytes:
        raise PayloadTooLargeError(max_bytes)
    return size
