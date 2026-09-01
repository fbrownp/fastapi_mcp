import json
import logging
import asyncio

from fastapi import Request, Response, HTTPException
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager, EventStore
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)


class FastApiHttpSessionManager:
    """
    FastAPI-native wrapper around StreamableHTTPSessionManager
    """

    def __init__(
        self,
        mcp_server: Server,
        event_store: EventStore | None = None,
        json_response: bool = True,  # Default to JSON for HTTP transport
        security_settings: TransportSecuritySettings | None = None,
        stateless: bool = False,
    ):
        self.mcp_server = mcp_server
        self.event_store = event_store
        self.json_response = json_response
        self.security_settings = security_settings
        # Stateless mode handles every request with a fresh transport and never
        # issues an mcp-session-id. Required when the app runs behind a load
        # balancer with multiple replicas/workers (e.g. Azure Container Apps):
        # stateful sessions live in one process's memory, so a follow-up POST
        # routed to a different replica is rejected before reaching the tools.
        self.stateless = stateless
        self._session_manager: StreamableHTTPSessionManager | None = None
        self._manager_task: asyncio.Task | None = None
        self._manager_started = False
        self._startup_lock = asyncio.Lock()

    async def _ensure_session_manager_started(self) -> None:
        """
        Ensure the session manager is started.

        This is called lazily on the first request to start the session manager
        if it hasn't been started yet.
        """
        if self._manager_started:
            return

        async with self._startup_lock:
            if self._manager_started:
                return

            logger.debug("Starting StreamableHTTP session manager")

            # Create the session manager
            # Note: We don't use stateless=True because we want to support sessions
            # but sessions are optional as per the MCP spec
            self._session_manager = StreamableHTTPSessionManager(
                app=self.mcp_server,
                event_store=self.event_store,
                json_response=self.json_response,
                stateless=self.stateless,
                security_settings=self.security_settings,
            )

            # Start the session manager in a background task
            async def run_session_manager():
                try:
                    async with self._session_manager.run():
                        logger.info("StreamableHTTP session manager is running")
                        # Keep running until cancelled
                        await asyncio.Event().wait()
                except asyncio.CancelledError:
                    logger.info("StreamableHTTP session manager is shutting down")
                    raise
                except Exception:
                    logger.exception("Error in StreamableHTTP session manager")
                    raise

            self._manager_task = asyncio.create_task(run_session_manager())
            self._manager_started = True

            # Give the session manager a moment to initialize
            await asyncio.sleep(0.1)

    async def handle_fastapi_request(self, request: Request) -> Response:
        """
        Handle a FastAPI request by delegating to the session manager.

        This converts FastAPI's Request/Response to ASGI scope/receive/send
        and then converts the result back to a FastAPI Response.
        """
        # Ensure session manager is started
        await self._ensure_session_manager_started()

        if not self._session_manager:
            raise HTTPException(status_code=500, detail="Session manager not initialized")

        logger.debug(f"Handling FastAPI request: {request.method} {request.url.path}")

        # Capture the response from the session manager
        response_started = False
        response_status = 200
        response_headers = []
        response_body = b""

        async def send_callback(message):
            nonlocal response_started, response_status, response_headers, response_body

            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                response_headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        try:
            # Delegate to the session manager's handle_request method
            await self._session_manager.handle_request(request.scope, request.receive, send_callback)

            # Convert the captured ASGI response to a FastAPI Response
            headers_dict = {name.decode(): value.decode() for name, value in response_headers}
            # The body may be rewritten below, so let Starlette recompute the length.
            headers_dict.pop("content-length", None)

            if response_status >= 400:
                response_status, response_body, headers_dict = self._normalize_error_response(
                    response_status, response_body, headers_dict
                )

            return Response(
                content=response_body,
                status_code=response_status,
                headers=headers_dict,
            )

        except Exception:
            logger.exception("Error in StreamableHTTPSessionManager")
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    def _normalize_error_response(
        status: int, body: bytes, headers: dict[str, str]
    ) -> tuple[int, bytes, dict[str, str]]:
        """
        Guarantee that error responses carry a JSON-RPC body.

        The underlying StreamableHTTP transport rejects some requests with a
        plain-text body and no Content-Type (e.g. 400 "Bad Request: No valid
        session ID provided" when a session ID is unknown to this process).
        MCP proxies that expect JSON-RPC on the wire (such as the Anthropic
        connector proxy) fail to parse that and surface an opaque
        -32600 "Invalid content from server" to the client instead of the real
        reason. An unknown session is also remapped from 400 to 404 so
        spec-compliant clients transparently re-initialize instead of erroring.
        """
        try:
            json.loads(body.decode())
            return status, body, headers  # Already a JSON body — pass through untouched.
        except (UnicodeDecodeError, ValueError):
            pass

        message = body.decode(errors="replace").strip() or "Internal server error"
        code = -32600
        if "session" in message.lower():
            # Per the Streamable HTTP spec, an expired/unknown session should
            # yield 404 so the client starts a new session with `initialize`.
            status = 404
            code = -32001

        error_body = json.dumps(
            {"jsonrpc": "2.0", "id": "server-error", "error": {"code": code, "message": message}}
        ).encode()
        headers = {**headers, "content-type": "application/json"}
        return status, error_body, headers

    async def shutdown(self) -> None:
        """Clean up the session manager and background task."""
        if self._manager_task and not self._manager_task.done():
            self._manager_task.cancel()
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
        self._manager_started = False
