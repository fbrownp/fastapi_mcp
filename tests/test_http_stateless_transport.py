"""
Tests for stateless Streamable HTTP mode and JSON-RPC error normalization.

Motivation: with the default stateful transport, sessions live in one process's
memory. Behind a load balancer with several replicas/workers (e.g. Azure
Container Apps), a follow-up POST routed to a different replica used to be
rejected with a plain-text 400 body ("Bad Request: No valid session ID
provided"). MCP proxies that expect JSON-RPC on the wire (such as the Anthropic
connector proxy) cannot parse that and surface an opaque -32600 "Invalid
content from server" to the client.
"""

import multiprocessing
import socket
import time
import os
import signal
import atexit
import sys
import threading
import coverage
from typing import AsyncGenerator, Generator
from fastapi import FastAPI
import pytest
import httpx
import uvicorn
from fastapi_mcp import FastApiMCP
import mcp.types as types


HOST = "127.0.0.1"
SERVER_NAME = "Test MCP Server"

JSON_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

CALL_TOOL_REQUEST = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 4,
    "params": {"name": "get_item", "arguments": {"item_id": 1}},
}


def run_server(server_port: int, fastapi_app: FastAPI, stateless: bool) -> None:
    # Initialize coverage for subprocesses
    cov = None
    if "COVERAGE_PROCESS_START" in os.environ:
        cov = coverage.Coverage(source=["fastapi_mcp"])
        cov.start()

        def cleanup():
            if cov:
                cov.stop()
                cov.save()

        atexit.register(cleanup)

        def handle_signal(signum, frame):
            cleanup()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)

        def periodic_save():
            while True:
                time.sleep(1.0)
                if cov:
                    cov.save()

        save_thread = threading.Thread(target=periodic_save)
        save_thread.daemon = True
        save_thread.start()

    mcp = FastApiMCP(
        fastapi_app,
        name=SERVER_NAME,
        description="Test description",
    )
    mcp.mount_http(stateless=stateless)

    server = uvicorn.Server(config=uvicorn.Config(app=fastapi_app, host=HOST, port=server_port, log_level="error"))
    server.run()

    while not server.started:
        time.sleep(0.5)

    if cov:
        cov.stop()
        cov.save()


def _make_server_fixture(stateless: bool):
    @pytest.fixture()
    def server(request: pytest.FixtureRequest) -> Generator[str, None, None]:
        coverage_rc = os.path.abspath(".coveragerc")
        os.environ["COVERAGE_PROCESS_START"] = coverage_rc

        with socket.socket() as s:
            s.bind((HOST, 0))
            server_port = s.getsockname()[1]

        ctx = multiprocessing.get_context("fork")

        fastapi_app = request.getfixturevalue("simple_fastapi_app")
        proc = ctx.Process(
            target=run_server,
            kwargs={"server_port": server_port, "fastapi_app": fastapi_app, "stateless": stateless},
            daemon=True,
        )
        proc.start()

        max_attempts = 20
        attempt = 0
        while attempt < max_attempts:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((HOST, server_port))
                    break
            except ConnectionRefusedError:
                time.sleep(0.1)
                attempt += 1
        else:
            raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

        yield f"http://{HOST}:{server_port}"

        try:
            proc.terminate()
            proc.join(timeout=2)
        except (OSError, AttributeError):
            pass

        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)
            if proc.is_alive():
                raise RuntimeError("server process failed to terminate")

    return server


stateless_server = _make_server_fixture(stateless=True)
stateful_server = _make_server_fixture(stateless=False)


@pytest.fixture()
async def stateless_client(stateless_server: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=stateless_server) as client:
        yield client


@pytest.fixture()
async def stateful_client(stateful_server: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=stateful_server) as client:
        yield client


@pytest.mark.anyio
async def test_stateless_initialize_issues_no_session_id(stateless_client: httpx.AsyncClient) -> None:
    response = await stateless_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
        headers=JSON_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers.get("mcp-session-id") is None
    result = response.json()
    assert result["result"]["serverInfo"]["name"] == SERVER_NAME


@pytest.mark.anyio
async def test_stateless_tool_call_without_prior_initialize(stateless_client: httpx.AsyncClient) -> None:
    """A bare tools/call must work with no session at all.

    This simulates the multi-replica scenario: the client initialized against
    one replica and this request landed on another that never saw it.
    """
    response = await stateless_client.post("/mcp", json=CALL_TOOL_REQUEST, headers=JSON_HEADERS)

    assert response.status_code == 200
    result = response.json()
    assert result["id"] == 4
    assert result["result"]["isError"] is False
    assert "Item 1" in result["result"]["content"][0]["text"]


@pytest.mark.anyio
async def test_stateful_unknown_session_returns_jsonrpc_404(stateful_client: httpx.AsyncClient) -> None:
    """An unknown session ID must yield a parseable JSON-RPC error, not plain text.

    It is also remapped to 404 so spec-compliant clients re-initialize instead of
    surfacing an opaque proxy error. mcp SDK versions up to at least 1.21.2 reply
    with a plain-text 400 body here (exercising _normalize_error_response); newer
    versions reply with 404 and a JSON-RPC body themselves, which passes through.
    Either way the client-visible contract below must hold.
    """
    response = await stateful_client.post(
        "/mcp",
        json=CALL_TOOL_REQUEST,
        headers={**JSON_HEADERS, "mcp-session-id": "deadbeefdeadbeefdeadbeefdeadbeef"},
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    result = response.json()
    assert result["jsonrpc"] == "2.0"
    assert result["error"]["code"] in (-32001, -32600)
    assert "session" in result["error"]["message"].lower()


@pytest.mark.anyio
async def test_stateful_missing_session_keeps_json_body(stateful_client: httpx.AsyncClient) -> None:
    """The SDK's own JSON-RPC error bodies must pass through untouched."""
    response = await stateful_client.post("/mcp", json=CALL_TOOL_REQUEST, headers=JSON_HEADERS)

    assert response.status_code in (400, 404)
    result = response.json()
    assert result["jsonrpc"] == "2.0"
    assert "error" in result


def test_normalize_error_response_wraps_plain_text_session_error():
    """The exact body mcp<=1.21.2 emits for an unknown session becomes JSON-RPC + 404."""
    from fastapi_mcp.transport.http import FastApiHttpSessionManager
    import json

    status, body, headers = FastApiHttpSessionManager._normalize_error_response(
        400, b"Bad Request: No valid session ID provided", {}
    )

    assert status == 404
    assert headers["content-type"] == "application/json"
    parsed = json.loads(body)
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["error"]["code"] == -32001
    assert parsed["error"]["message"] == "Bad Request: No valid session ID provided"


def test_normalize_error_response_wraps_other_plain_text():
    """Non-session plain-text errors keep their status but gain a JSON-RPC body."""
    from fastapi_mcp.transport.http import FastApiHttpSessionManager
    import json

    status, body, headers = FastApiHttpSessionManager._normalize_error_response(406, b"Not Acceptable", {})

    assert status == 406
    parsed = json.loads(body)
    assert parsed["error"]["code"] == -32600
    assert parsed["error"]["message"] == "Not Acceptable"


def test_normalize_error_response_passes_json_through():
    """JSON-RPC bodies produced by the SDK itself are never rewritten."""
    from fastapi_mcp.transport.http import FastApiHttpSessionManager

    original = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32700,"message":"Parse error"}}'
    status, body, headers = FastApiHttpSessionManager._normalize_error_response(
        400, original, {"content-type": "application/json"}
    )

    assert status == 400
    assert body == original
