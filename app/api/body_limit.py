from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from starlette.types import Message

from app.core.config import Settings
from app.core.errors import PayloadTooLargeError

# Room for the multipart boundaries and part headers that surround the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def body_limited_route(max_file_bytes: Callable[[Settings], int]) -> type[APIRoute]:
    """Route class that rejects an oversized request body before FastAPI parses it.

    FastAPI reads the whole multipart body to a temporary file before it runs
    dependencies such as authentication, so a limit checked in the service comes
    too late to protect the server's disk.
    """

    class BodyLimitedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def limited_handler(request: Request) -> Response:
                max_file = max_file_bytes(request.app.state.settings)
                limit = max_file + MULTIPART_OVERHEAD_BYTES

                def too_large() -> HTTPException:
                    # FastAPI turns any other exception raised while parsing into a 400.
                    return HTTPException(
                        status_code=413,
                        detail=PayloadTooLargeError(max_file).message,
                    )

                declared = request.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    raise too_large()

                # Content-Length can be absent (chunked), so count what actually arrives.
                received = 0

                async def receive() -> Message:
                    nonlocal received
                    message = await request.receive()
                    if message["type"] == "http.request":
                        received += len(message.get("body", b""))
                        if received > limit:
                            raise too_large()
                    return message

                return await handler(Request(request.scope, receive))

            return limited_handler

    return BodyLimitedRoute
