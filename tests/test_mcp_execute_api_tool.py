import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import FastAPI

from fastapi_mcp import FastApiMCP
from mcp.types import TextContent


@pytest.mark.asyncio
async def test_execute_api_tool_success(simple_fastapi_app: FastAPI):
    """Test successful execution of an API tool."""
    mcp = FastApiMCP(simple_fastapi_app)

    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": 1, "name": "Test Item"}
    mock_response.status_code = 200
    mock_response.text = '{"id": 1, "name": "Test Item"}'

    # Mock the HTTP client
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Test parameters
    tool_name = "get_item"
    arguments = {"item_id": 1}

    # Execute the tool
    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client, tool_name=tool_name, arguments=arguments, operation_map=mcp.operation_map
        )

    # Verify the result (a CallToolResult with a single text content block)
    assert result.isError is False
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == '{\n  "id": 1,\n  "name": "Test Item"\n}'

    # Verify the HTTP client was called correctly
    mock_client.get.assert_called_once_with("/items/1", params={}, headers={})


@pytest.mark.asyncio
async def test_execute_api_tool_with_query_params(simple_fastapi_app: FastAPI):
    """Test execution of an API tool with query parameters."""
    mcp = FastApiMCP(simple_fastapi_app)

    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]
    mock_response.status_code = 200
    mock_response.text = '[{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]'

    # Mock the HTTP client
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Test parameters
    tool_name = "list_items"
    arguments = {"skip": 0, "limit": 2}

    # Execute the tool
    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client, tool_name=tool_name, arguments=arguments, operation_map=mcp.operation_map
        )

    # Verify the result (a CallToolResult with a single text content block)
    assert result.isError is False
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)

    # Verify the HTTP client was called with query parameters
    mock_client.get.assert_called_once_with("/items/", params={"skip": 0, "limit": 2}, headers={})


@pytest.mark.asyncio
async def test_execute_api_tool_with_body(simple_fastapi_app: FastAPI):
    """Test execution of an API tool with request body."""
    mcp = FastApiMCP(simple_fastapi_app)

    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": 1, "name": "New Item"}
    mock_response.status_code = 200
    mock_response.text = '{"id": 1, "name": "New Item"}'

    # Mock the HTTP client
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    # Test parameters
    tool_name = "create_item"
    arguments = {
        "item": {"id": 1, "name": "New Item", "price": 10.0, "tags": ["tag1"], "description": "New item description"}
    }

    # Execute the tool
    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client, tool_name=tool_name, arguments=arguments, operation_map=mcp.operation_map
        )

    # Verify the result (a CallToolResult with a single text content block)
    assert result.isError is False
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)

    # Verify the HTTP client was called with the request body
    mock_client.post.assert_called_once_with("/items/", params={}, headers={}, json=arguments)


@pytest.mark.asyncio
async def test_execute_api_tool_sends_empty_json_body_when_operation_declares_required_request_body(
    simple_fastapi_app: FastAPI,
):
    """A zero-argument call still POSTs `{}` when the operation declares a *required* requestBody.

    Regression test: an endpoint's body parameter can be a *required* Pydantic model with zero
    fields of its own (e.g. every field it would need comes from headers instead) -- calling such
    a tool with no leftover ``arguments`` after path/query/header extraction used to send no HTTP
    body at all (``body = arguments if arguments else None``), which such an endpoint 422s
    ``Field required`` on. Gating on the operation's own declared ``request_body`` being marked
    ``required`` (populated from the OpenAPI ``requestBody``, see ``openapi/convert.py``) instead
    sends ``{}``, which validates fine either way. ``simple_fastapi_app`` is only used to construct
    a real ``FastApiMCP`` instance; the operation itself is a synthetic ``operation_map`` entry so
    this test never needs a real zero-field-body route on the shared fixture app (which several
    other tests assert an exact operation count/list against).
    """
    mcp = FastApiMCP(simple_fastapi_app)

    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.status_code = 200
    mock_response.text = '{"ok": true}'

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    operation_map = {
        "zero_arg_with_body": {
            "path": "/scope-only",
            "method": "post",
            "parameters": [],
            "request_body": {
                "required": True,
                "content": {"application/json": {"schema": {"type": "object"}}},
            },
            "_meta": {},
        }
    }

    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client,
            tool_name="zero_arg_with_body",
            arguments={},
            operation_map=operation_map,
        )

    assert result.isError is False
    mock_client.post.assert_called_once_with("/scope-only", params={}, headers={}, json={})


@pytest.mark.asyncio
async def test_execute_api_tool_sends_no_body_when_operation_declares_optional_request_body(
    simple_fastapi_app: FastAPI,
):
    """A zero-argument call sends no HTTP body when the requestBody is declared but optional.

    Regression test for the fix above: FastAPI declares a requestBody (without
    ``required: true``) for an *optional* body param too (``body: Model | None = None``). Gating
    only on presence of a declared requestBody would resend ``{}`` for these, which 422s on a
    required-field model exposed as optional, or silently swaps a handler's ``body is None``
    branch for an instantiated-with-defaults model. The fix must key off ``required`` instead, so
    a zero-argument call to an optional-body operation keeps sending no body, exactly as an
    operation with no requestBody at all does.
    """
    mcp = FastApiMCP(simple_fastapi_app)

    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.status_code = 200
    mock_response.text = '{"ok": true}'

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    operation_map = {
        "zero_arg_with_optional_body": {
            "path": "/optional-scope",
            "method": "post",
            "parameters": [],
            "request_body": {
                "content": {
                    "application/json": {
                        "schema": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                    }
                },
            },
            "_meta": {},
        }
    }

    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client,
            tool_name="zero_arg_with_optional_body",
            arguments={},
            operation_map=operation_map,
        )

    assert result.isError is False
    mock_client.post.assert_called_once_with("/optional-scope", params={}, headers={}, json=None)


@pytest.mark.asyncio
async def test_execute_api_tool_sends_no_body_when_operation_declares_no_request_body(
    simple_fastapi_app: FastAPI,
):
    """A zero-argument call still sends no HTTP body when the operation has no requestBody at all.

    Unchanged behavior: a ``delete_item``-shaped operation (no request body declared) must never
    gain a spurious ``{}`` body from the fix under test above.
    """
    mcp = FastApiMCP(simple_fastapi_app)

    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.status_code = 200
    mock_response.text = "{}"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    operation_map = {
        "zero_arg_no_body": {
            "path": "/no-body",
            "method": "post",
            "parameters": [],
            "request_body": {},
            "_meta": {},
        }
    }

    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client,
            tool_name="zero_arg_no_body",
            arguments={},
            operation_map=operation_map,
        )

    assert result.isError is False
    mock_client.post.assert_called_once_with("/no-body", params={}, headers={}, json=None)


@pytest.mark.asyncio
async def test_execute_api_tool_sends_empty_body_end_to_end_through_real_convert_pipeline():
    """End-to-end regression test for the `{}`-body fix, through the real convert -> execute path.

    The two tests above hand-build a synthetic `operation_map` entry, which pins the fix to a
    convention (`convert.py` stores the OpenAPI `requestBody` under the key ``"request_body"``,
    with a falsy value meaning "undeclared") without ever exercising the code that establishes
    that convention. This test instead builds a fresh `FastAPI()` app with a real zero-field,
    *required* body route, runs it through `FastApiMCP.__init__` (which calls
    `convert_openapi_to_mcp_tools` for real), and asserts the zero-argument `_execute_api_tool`
    call POSTs `{}` -- so a future rename or reshape of `convert.py`'s `operation_map` contract
    breaks this test too, not just the synthetic-fixture ones.
    """
    from pydantic import BaseModel

    class ScopeOnlyBody(BaseModel):
        pass

    app = FastAPI()

    @app.post("/scope-only", operation_id="scope_only_tool")
    async def scope_only(body: ScopeOnlyBody):
        return {"ok": True}

    mcp = FastApiMCP(app)
    assert "scope_only_tool" in mcp.operation_map
    assert mcp.operation_map["scope_only_tool"]["request_body"]["required"] is True

    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True}
    mock_response.status_code = 200
    mock_response.text = '{"ok": true}'

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client,
            tool_name="scope_only_tool",
            arguments={},
            operation_map=mcp.operation_map,
        )

    assert result.isError is False
    mock_client.post.assert_called_once_with("/scope-only", params={}, headers={}, json={})


@pytest.mark.asyncio
async def test_execute_api_tool_with_non_ascii_chars(simple_fastapi_app: FastAPI):
    """Test execution of an API tool with non-ASCII characters."""
    mcp = FastApiMCP(simple_fastapi_app)

    # Test data with both ASCII and non-ASCII characters
    test_data = {
        "id": 1,
        "name": "你好 World",  # Chinese characters + ASCII
        "price": 10.0,
        "tags": ["tag1", "标签2"],  # Chinese characters in tags
        "description": "这是一个测试描述",  # All Chinese characters
    }

    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = test_data
    mock_response.status_code = 200
    mock_response.text = (
        '{"id": 1, "name": "你好 World", "price": 10.0, "tags": ["tag1", "标签2"], "description": "这是一个测试描述"}'
    )

    # Mock the HTTP client
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Test parameters
    tool_name = "get_item"
    arguments = {"item_id": 1}

    # Execute the tool
    with patch.object(mcp, "_http_client", mock_client):
        result = await mcp._execute_api_tool(
            client=mock_client, tool_name=tool_name, arguments=arguments, operation_map=mcp.operation_map
        )

    # Verify the result (a CallToolResult with a single text content block)
    assert result.isError is False
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)

    # Verify that the response contains both ASCII and non-ASCII characters
    response_text = result.content[0].text
    assert "你好" in response_text  # Chinese characters preserved
    assert "World" in response_text  # ASCII characters preserved
    assert "标签2" in response_text  # Chinese characters in tags preserved
    assert "这是一个测试描述" in response_text  # All Chinese description preserved

    # Verify the HTTP client was called correctly
    mock_client.get.assert_called_once_with("/items/1", params={}, headers={})
