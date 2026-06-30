from __future__ import annotations

import logging
import math
import os
from typing import Any

from fastmcp import FastMCP

from tools.healthcare_knowledge_tools import (
    HEALTHCARE_PROJECT_ID,
    PROJECT_ALIASES,
    HealthcareMcpConfig,
    HealthcareProjectTools,
    hydrate_env_from_aws_secret,
)


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mcp_tools")

secret_hydration = hydrate_env_from_aws_secret()
if secret_hydration.get("loaded"):
    logger.info(
        "mcp_runtime_secret_loaded secret=%s keys=%s skipped_keys=%s",
        secret_hydration.get("secret_name"),
        ",".join(secret_hydration.get("keys") or []),
        ",".join(secret_hydration.get("skipped_keys") or []),
    )
else:
    logger.info("mcp_runtime_secret_skipped reason=%s", secret_hydration.get("reason"))

mcp = FastMCP("DstrMaysam MCP Tools")
HEALTHCARE_TOOLS = HealthcareProjectTools(HealthcareMcpConfig.from_env())


def _validate_project(project_id: str) -> str | None:
    if project_id not in PROJECT_ALIASES:
        logger.warning("mcp_tool_request rejected project=%s", project_id)
        return f"Project {project_id!r} is not registered on this MCP server."
    return None


def _run_healthcare_tool(project_id: str, tool_name: str, payload: dict[str, Any]) -> str:
    logger.info("mcp_tool_request project=%s tool=%s", project_id, tool_name)
    validation_error = _validate_project(project_id)
    if validation_error:
        return validation_error
    return HEALTHCARE_TOOLS.execute(tool_name, payload)


@mcp.tool()
def postgres_deterministic_lookup(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Run exact table-backed lookup for patients, doctors, rota, contacts, appointments, wards, formulary, and assets."""
    return _run_healthcare_tool(project_id, "postgres_deterministic_lookup", payload)


@mcp.tool()
def calendar_rota_lookup(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Run table-backed rota, on-call, clinic, and schedule lookup."""
    return _run_healthcare_tool(project_id, "calendar_rota_lookup", payload)


@mcp.tool()
def formulary_table_lookup(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Run exact table-backed formulary lookup."""
    return _run_healthcare_tool(project_id, "formulary_table_lookup", payload)


@mcp.tool()
def table_lookup(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Run generic table lookup for callers that still use the legacy table_lookup tool name."""
    return _run_healthcare_tool(project_id, "table_lookup", payload)


@mcp.tool()
def document_search(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Search approved document content for the healthcare project."""
    return _run_healthcare_tool(project_id, "document_search", payload)


@mcp.tool()
def rag_search(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Search approved document content using the legacy rag_search tool name."""
    return _run_healthcare_tool(project_id, "rag_search", payload)


@mcp.tool()
def policy_search(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Search approved policy, SOP, pathway, and guideline content."""
    return _run_healthcare_tool(project_id, "policy_search", payload)


@mcp.tool()
def catalogue_search(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Search approved document and service catalogue metadata."""
    return _run_healthcare_tool(project_id, "catalogue_search", payload)


@mcp.tool()
def document_catalog(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Search approved document catalogue metadata using the legacy document_catalog tool name."""
    return _run_healthcare_tool(project_id, "document_catalog", payload)


@mcp.tool()
def safety_guard(
    payload: dict[str, Any],
    project_id: str = HEALTHCARE_PROJECT_ID,
) -> str:
    """Run healthcare safety, escalation, PHI, and missing-source checks."""
    return _run_healthcare_tool(project_id, "safety_guard", payload)


@mcp.tool()
def add(a: float, b: float) -> float:
    """Shared calculator POC tool: add two numbers."""
    logger.info("mcp_tool_request project=shared tool=add")
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Shared calculator POC tool: subtract b from a."""
    logger.info("mcp_tool_request project=shared tool=subtract")
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Shared calculator POC tool: multiply two numbers."""
    logger.info("mcp_tool_request project=shared tool=multiply")
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Shared calculator POC tool: divide a by b."""
    logger.info("mcp_tool_request project=shared tool=divide")
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


@mcp.tool()
def sqrt(n: float) -> float:
    """Shared calculator POC tool: square root."""
    logger.info("mcp_tool_request project=shared tool=sqrt")
    if n < 0:
        raise ValueError("Cannot take square root of a negative number")
    return math.sqrt(n)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "9000"))
    mcp.run(transport="sse", host=host, port=port)
