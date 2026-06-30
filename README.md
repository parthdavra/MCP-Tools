# MCP Tools Server

FastMCP server for shared and project-specific tool execution.

## Current Projects

- `dstrmaysam-healthcare-knowledge-multi-agent`

The healthcare backend still performs supervisor routing, agent selection, and tool selection. When configured for MCP mode, it calls the selected MCP tool here directly; this server performs only the tool execution and returns the result.

The healthcare tools follow the same execution flow as the backend tools:

1. Validate project id.
2. Read the selected agent tool payload.
3. Apply role/access filtering from `user_context`.
4. Execute the selected tool against local or AWS resources.
5. Return the same style of tool evidence to the backend for synthesis.

## Run Locally

```bash
docker compose up --build
```

SSE endpoint:

```text
http://localhost:9000/sse
```

## Healthcare Tool Config

The MCP server has a local/AWS switch:

```env
MCP_APP_ENV=local
```

Use `MCP_APP_ENV=local` for local Postgres plus the mounted local document manifest/files. Use `MCP_APP_ENV=dev` or another non-local value in AWS so tool execution uses AWS resources.

In AWS mode, the MCP server hydrates its runtime environment from Secrets Manager before registering tools:

```env
MCP_APP_ENV=dev
MCP_SECRET_NAME=/dstrmaysam-healthcare-knowledge-multi-agent-dev/mcp-tools
AWS_REGION=eu-west-2
AWS_PROFILE=default
```

The MCP secret should contain the full set of runtime variables used by this repo's `.env`, including Postgres, S3, OpenSearch, Azure OpenAI secret reference, RAG settings, and project defaults. The server logs the loaded key names only; secret values are not logged.

When running AWS mode locally through Docker Compose, the container still needs AWS credentials before it can read the MCP secret. Compose supports either:

- standard AWS environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional `AWS_SESSION_TOKEN`
- a local AWS profile mounted read-only from `%USERPROFILE%/.aws` and selected with `AWS_PROFILE`

In ECS, do not provide long-lived keys. Use the MCP task role instead.

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

AWS document/RAG config:

```env
AWS_REGION=eu-west-2
S3_BUCKET=dstrmaysam-healthcare-knowledge-multi-agent-dev
S3_RAW_PREFIX=raw/
HEALTHCARE_MANIFEST_KEY=manifests/documents.json
OPENSEARCH_ENDPOINT=https://YOUR-AOSS-ENDPOINT.eu-west-2.aoss.amazonaws.com
OPENSEARCH_INDEX=dstrmaysam-healthcare-knowledge-multi-agent-dev
AZURE_OPENAI_SECRET_NAME=/dstrmaysam-healthcare-knowledge-multi-agent-dev/azure-openai
RAG_TOP_K=10
RAG_NEIGHBOR_CHUNKS=1
```

In AWS mode, the MCP server expects its task role or runtime credentials to allow:

- `secretsmanager:GetSecretValue` for the Azure OpenAI secret
- `s3:GetObject` for the document manifest and raw documents
- OpenSearch Serverless data access for the configured index
- network access to RDS Postgres

The RDS password can be injected as `POSTGRES_PASSWORD` from Secrets Manager, the same way the backend task receives it.

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
