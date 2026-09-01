# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `mount_http(stateless=...)` and `FastApiHttpSessionManager(stateless=...)`: opt-in stateless Streamable HTTP mode. Every request is handled by a fresh transport and no `mcp-session-id` is issued or required, making the server safe behind load balancers with multiple replicas/workers (e.g. Azure Container Apps), where in-memory sessions caused follow-up requests routed to a different replica to fail.
- `mount_http(json_response=...)` passthrough to the underlying transport.

### Fixed
- Error responses from the Streamable HTTP transport are now always valid JSON-RPC. Older `mcp` SDK versions reject an unknown session with a plain-text 400 body ("Bad Request: No valid session ID provided"); MCP proxies that expect JSON-RPC on the wire (such as the Anthropic connector proxy) could not parse it and surfaced an opaque `-32600 "Anthropic Proxy: Invalid content from server"` to the client. Unknown sessions are also remapped to 404 so spec-compliant clients re-initialize transparently.
- Top-level union request bodies (e.g. `body: Annotated[Union[A, B], Field(discriminator='scope')]`) no longer convert to an empty tool input schema. The tool now advertises the union branches (with their discriminator) plus merged top-level property hints, so schema-abiding clients stop calling such tools with `{}` and getting `Field required` validation errors.
- Empty response bodies (e.g. 204 No Content) no longer render as the bytes repr `b''` in tool result text.
- Bumped the `mcp` dependency floor to `>=1.21.2,<2`. Older versions lack the `CallToolResult` passthrough in the `call_tool` handler and mangle every tool result into a "20 validation errors for CallToolResult" error.

## [0.4.0]

🚀 **FastAPI-MCP now supports Streamable HTTP transport.**

HTTP transport is now the recommended approach, following the specification that positions HTTP as the standard while maintaining SSE for backwards compatibility.

### ⚠️ Breaking Changes
- **`mount()` method is deprecated** and will be removed in a future version. Use `mount_http()` for HTTP transport (recommended) or `mount_sse()` for SSE transport.

### Added
- 🎉 **Streamable HTTP Transport Support** - New `mount_http()` method implementing the MCP Streamable HTTP specification
- 🎉 **Stateful Session Management** - For both HTTP and SSE transports

## [0.3.7]

### Fixed
- 🐛 Fix a bug with OAuth default_scope (#123)

## [0.3.6]

Skipped 0.3.5 due to a broken release attempt.

### Added
- 🚀 Add configurable HTTP header forwarding (#181)

### Fixed
- 🐛 Fix a bug with handling FastAPI `root_path` parameter (#163)

## [0.3.4]

### Fixed
- 🐛 Update the `mcp` dependency to `1.8.1`. Fixes [Issue #134](https://github.com/tadata-org/fastapi_mcp/issues/134) that was caused after a breaking change in mcp sdk 1.8.0.

## [0.3.3]

Fixes the broken release from 0.3.2.

### Fixed
- 🐛 Fix critical bug in openapi conversion (missing `param_desc` definition) (#107, #99)
- 🐛 Fix non-ascii support (#66)

## [0.3.2] - Broken

This is a broken release and should not be used.

### Fixed
- 🐛 Fix a bug preventing simple setup of [basic token passthrough](docs/03_authentication_and_authorization.md#basic-token-passthrough)

## [0.3.1]

🚀 FastApiMCP now supports MCP Authorization!

You can now add MCP-compliant OAuth configuration in a FastAPI-native way, using your existing FastAPI `Depends()` that we all know and love.

### Added
- 🎉 Support for Authentication / Authorization compliant to [MCP 2025-03-26 Specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization), using OAuth 2.1. (#10)
- 🎉 Support passing http headers to tool calls (#82)

## [0.3.0]

🚀 FastApiMCP now works with ASGI-transport by default.

This means the `base_url` argument is redundant, and thus has been removed.

You can still set up an explicit base URL using the `http_client` argument, and injecting your own `httpx.AsyncClient` if necessary.

### Removed
- ⚠️ Breaking Change: Removed `base_url` argument since it's not used anymore by the MCP transport.

### Fixed
- 🐛 Fix short timeout issue (#71), increasing the default timeout to 10


## [0.2.0]

### Changed
- Complete refactor from function-based API to a new class-based API with `FastApiMCP`
- Explicit separation between MCP instance creation and mounting with `mcp = FastApiMCP(app)` followed by `mcp.mount()`
- FastAPI-native approach for transport providing more flexible routing options
- Updated minimum MCP dependency to v1.6.0

### Added
- Support for deploying MCP servers separately from API service
- Support for "refreshing" with `setup_server()` when dynamically adding FastAPI routes. Fixes [Issue #19](https://github.com/tadata-org/fastapi_mcp/issues/19)
- Endpoint filtering capabilities through new parameters:
  - `include_operations`: Expose only specific operations by their operation IDs
  - `exclude_operations`: Expose all operations except those with specified operation IDs
  - `include_tags`: Expose only operations with specific tags
  - `exclude_tags`: Expose all operations except those with specific tags

### Fixed
- FastAPI-native approach for transport. Fixes [Issue #28](https://github.com/tadata-org/fastapi_mcp/issues/28)
- Numerous bugs in OpenAPI schema to tool conversion, addressing [Issue #40](https://github.com/tadata-org/fastapi_mcp/issues/40) and [Issue #45](https://github.com/tadata-org/fastapi_mcp/issues/45)

### Removed
- Function-based API (`add_mcp_server`, `create_mcp_server`, etc.)
- Custom tool support via `@mcp.tool()` decorator

## [0.1.8]

### Fixed
- Remove unneeded dependency.

## [0.1.7]

### Fixed
- [Issue #34](https://github.com/tadata-org/fastapi_mcp/issues/34): Fix syntax error.

## [0.1.6]

### Fixed
- [Issue #23](https://github.com/tadata-org/fastapi_mcp/issues/23): Hide handle_mcp_connection tool.

## [0.1.5]

### Fixed
- [Issue #25](https://github.com/tadata-org/fastapi_mcp/issues/25): Dynamically creating tools function so tools are useable.

## [0.1.4]

### Fixed
- [Issue #8](https://github.com/tadata-org/fastapi_mcp/issues/8): Converted tools unuseable due to wrong passing of arguments.

## [0.1.3]

### Fixed
- Dependency resolution issue with `mcp` package and `pydantic-settings`

## [0.1.2]

### Changed
- Complete refactor: transformed from a code generator to a direct integration library
- Replaced the CLI-based approach with a direct API for adding MCP servers to FastAPI applications
- Integrated MCP servers now mount directly to FastAPI apps at runtime instead of generating separate code
- Simplified the API with a single `add_mcp_server` function for quick integration
- Removed code generation entirely in favor of runtime integration

### Added
- Main `add_mcp_server` function for simple MCP server integration
- Support for adding custom MCP tools alongside API-derived tools
- Improved test suite
- Manage with uv

### Removed
- CLI interface and all associated commands (generate, run, install, etc.)
- Code generation functionality

## [0.1.1] - 2024-07-03

### Fixed
- Added support for PEP 604 union type syntax (e.g., `str | None`) in FastAPI endpoints
- Improved type handling in model field generation for newer Python versions (3.10+)
- Fixed compatibility issues with modern type annotations in path parameters, query parameters, and Pydantic models

## [0.1.0] - 2024-03-08

### Added
- Initial release of FastAPI-MCP
- Core functionality for converting FastAPI applications to MCP servers
- CLI tool for generating, running, and installing MCP servers
- Automatic discovery of FastAPI endpoints
- Type-safe conversion from FastAPI endpoints to MCP tools
- Documentation preservation from FastAPI to MCP
- Claude integration for easy installation and use
- API integration that automatically makes HTTP requests to FastAPI endpoints
- Examples directory with sample FastAPI application
- Basic test suite