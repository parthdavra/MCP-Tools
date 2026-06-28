# MCP Tools Server

FastMCP server for shared and project-specific tool execution.

## Current Projects

- `dstrmaysam-healthcare-knowledge-multi-agent`

The healthcare backend still performs supervisor routing, agent selection, and tool selection. When configured for MCP mode, it calls the selected MCP tool here directly; this server performs only the tool execution and returns the result.

## Run Locally

```bash
docker compose up --build
```

SSE endpoint:

```text
http://localhost:9000/sse
```

## Healthcare Tool Config

Required for table-backed deterministic lookup:

```env
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432
POSTGRES_DB=healthcare_agent
POSTGRES_USER=healthcare_agent
POSTGRES_PASSWORD=healthcare_agent_dev
POSTGRES_SSLMODE=disable
```

Optional local document search config:

```env
HEALTHCARE_LOCAL_DATA_DIR=/app/data
HEALTHCARE_MANIFEST_KEY=manifests/documents.json
```

## Backend Switch

In the healthcare backend:

```env
TOOL_EXECUTION_MODE=mcp
MCP_SERVER_URL=http://host.docker.internal:9000/sse
MCP_PROJECT_ID=dstrmaysam-healthcare-knowledge-multi-agent
```

Use `TOOL_EXECUTION_MODE=local` to keep tool execution inside the backend.

The server logs every request with the project and tool name, for example:

```text
mcp_tool_request project=dstrmaysam-healthcare-knowledge-multi-agent tool=postgres_deterministic_lookup
```

## Adding More Projects

Add project tool logic in its own module, then register each callable in `src/mcp_tools_server.py` with `@mcp.tool()`. Keep tool names stable so caller systems can continue doing their own agent/tool selection and only delegate execution.
