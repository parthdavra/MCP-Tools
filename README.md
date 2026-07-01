# MCP Tools Server

FastMCP server for shared and project-specific tool execution.

## Current Projects

- `dstrmaysam-healthcare-knowledge-multi-agent`
- `finpilot`

The healthcare backend still performs supervisor routing, agent selection, and tool selection. When configured for MCP mode, it calls the selected MCP tool here directly; this server performs only the tool execution and returns the result.

The healthcare tools follow the same execution flow as the backend tools:

1. Validate project id.
2. Read the selected agent tool payload.
3. Apply role/access filtering from `user_context`.
4. Execute the selected tool against local or AWS resources.
5. Return the same style of tool evidence to the backend for synthesis.

Deterministic Postgres lookup is shared with the healthcare backend through the `healthcare-tools-core` Python package. The package source lives in the healthcare repo under:

```text
backend/packages/healthcare_tools_core
```

For local development, this repo can import that package from the sibling healthcare checkout. Docker and AWS builds install it from the healthcare GitHub repo through `requirements.txt`, so push the healthcare repo package changes before running the MCP pipeline.

## Run Locally

```bash
docker compose up --build
```

SSE endpoint:

```text
http://localhost:9000/sse
```

FinPilot also uses the same MCP-Tools process as the single shared tool server. FastMCP exposes the FinPilot tools on the SSE endpoint, and the local Streamlit app can call the lightweight HTTP bridge on the health server:

```text
http://localhost:9001/finpilot/tool
```

Set this in the FinPilot app environment:

```env
FINPILOT_MCP_TOOL_URL=http://localhost:9001/finpilot/tool
```

Set this in the MCP-Tools server environment when the FinPilot checkout is not the default sibling folder:

```env
FINPILOT_PROJECT_ROOT=C:\Harshasree\Assignments\FinPilot
```

The registered FinPilot MCP tools are:

- `finpilot_resolve_symbol`
- `finpilot_market_snapshot`
- `finpilot_price_history`
- `finpilot_company_profile`
- `finpilot_company_financials`
- `finpilot_competitor_analysis`
- `finpilot_latest_news`
- `finpilot_latest_earnings`
- `finpilot_top_stocks`
- `finpilot_market_status`
- `finpilot_buying_power`
- `finpilot_search_documents`

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

## Deploy Into Healthcare AWS VPC

The healthcare project CloudFormation stack owns the MCP runtime infrastructure for the dev environment:

- ECR repository `dstrmaysam-healthcare-knowledge-multi-agent-dev-mcp`
- ECS/Fargate service `dstrmaysam-healthcare-knowledge-multi-agent-dev-mcp`
- Cloud Map URL `http://mcp-tools.dstrmaysam-hkm-dev.local:9000/sse`
- Public dev ALB URL from the healthcare stack `McpPublicUrl` output
- MCP task role, security group, RDS ingress, log group, and OpenSearch Serverless access policy principal

This repo owns only the MCP image build and service deployment. The pipeline template is:

```text
infra/mcp-pipeline.yml
```

The MCP pipeline uses a GitHub CodeStar connection, builds the Docker image, pushes both `mcp-<commit>` and `mcp-latest`, emits `imagedefinitions.json` for the `mcp-tools` container, and updates only the MCP ECS service created by the healthcare stack.

Deploy order:

1. Deploy or update the healthcare stack with `McpDesiredCount=0`.
2. Copy these healthcare stack outputs into the MCP pipeline parameters:
   - `McpEcrRepositoryUri`
   - `EcsClusterName`
   - `McpServiceName`
   - `EcsExecutionRoleArn`
   - `McpTaskRoleArn`
3. Deploy `infra/mcp-pipeline.yml` from this repo.
4. Run the MCP pipeline so it pushes `mcp-latest`.
5. Update the healthcare stack with `McpDesiredCount=1`.
6. Set the healthcare backend app secret to use `tool_execution_mode=mcp` and `mcp_server_url=http://mcp-tools.dstrmaysam-hkm-dev.local:9000/sse`.
7. Use the healthcare stack `McpPublicUrl` output for dev calls from outside the VPC.

The backend should use the private Cloud Map URL when it runs in the same VPC. The public ALB URL is for dev/external access and is controlled by the healthcare stack `PublicIngressCidr` parameter.

## Adding More Projects

Add project tool logic in its own module, then register each callable in `src/mcp_tools_server.py` with `@mcp.tool()`. Keep tool names stable so caller systems can continue doing their own agent/tool selection and only delegate execution.
