from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


FINPILOT_PROJECT_ID = "finpilot"


@dataclass(frozen=True)
class FinPilotMcpConfig:
    project_root: Path

    @classmethod
    def from_env(cls) -> "FinPilotMcpConfig":
        configured = os.getenv("FINPILOT_PROJECT_ROOT")
        if configured:
            return cls(project_root=Path(configured).expanduser().resolve())

        return cls(project_root=Path(__file__).resolve().parents[3] / "FinPilot")


class FinPilotProjectTools:
    """Central MCP tool adapter for FinPilot's financial data facade."""

    def __init__(self, config: FinPilotMcpConfig) -> None:
        self.config = config
        self._server: Any | None = None

    def execute(self, tool_name: str, payload: dict[str, Any]) -> str:
        tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "finpilot_resolve_symbol": self.resolve_symbol,
            "finpilot_market_snapshot": self.market_snapshot,
            "finpilot_price_history": self.price_history,
            "finpilot_company_profile": self.company_profile,
            "finpilot_company_financials": self.company_financials,
            "finpilot_competitor_analysis": self.competitor_analysis,
            "finpilot_latest_news": self.latest_news,
            "finpilot_latest_earnings": self.latest_earnings,
            "finpilot_top_stocks": self.top_stocks,
            "finpilot_market_status": self.market_status,
            "finpilot_buying_power": self.buying_power,
            "finpilot_search_documents": self.search_documents,
        }
        if tool_name not in tools:
            return json.dumps({"ok": False, "error": f"Unknown FinPilot tool: {tool_name}"})
        try:
            return json.dumps({"ok": True, "data": tools[tool_name](payload)}, default=str)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})

    def resolve_symbol(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.resolve_symbol(str(payload.get("query", "")), market=payload.get("market"))

    def market_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.market_snapshot(self._ticker(payload))

    def price_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.price_history(self._ticker(payload), str(payload.get("horizon") or "3 months"))

    def company_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.company_profile(self._ticker(payload))

    def company_financials(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.company_financials(self._ticker(payload))

    def competitor_analysis(self, payload: dict[str, Any]) -> list[str]:
        return self.server.competitor_analysis(self._ticker(payload))

    def latest_news(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return self.server.latest_news(self._ticker(payload))

    def latest_earnings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.latest_earnings(self._ticker(payload))

    def top_stocks(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.top_stocks(str(payload.get("market") or "India"), int(payload.get("limit") or 10))

    def market_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.server.market_status()

    def buying_power(self, payload: dict[str, Any]) -> float:
        return self.server.buying_power()

    def search_documents(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return self.server.search_documents(str(payload.get("query", "")))

    @property
    def server(self) -> Any:
        if self._server is None:
            self._add_finpilot_to_path()
            from finpilot.core.settings import Settings
            from finpilot_mcp.server import FinancialIntelligenceServer

            self._server = FinancialIntelligenceServer(Settings.from_env())
        return self._server

    def _add_finpilot_to_path(self) -> None:
        src = self.config.project_root / "src"
        if not src.exists():
            raise RuntimeError(
                "FinPilot source path was not found. Set FINPILOT_PROJECT_ROOT to the FinPilot checkout path."
            )
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))

    def _ticker(self, payload: dict[str, Any]) -> str:
        ticker = str(payload.get("ticker") or "").strip()
        if not ticker:
            raise ValueError("ticker is required")
        return ticker.upper()
