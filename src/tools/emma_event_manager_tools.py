"""
Event Manager MCP Tools
=======================
Self-contained tool module that can be:
  1. Hosted on the shared MCP server (copy/link this file to mcp_server/src/tools/)
  2. Used as an in-process fallback inside the FastAPI app when the MCP server is unavailable.

No top-level imports from `app.*` — all app-layer integrations are lazy so this file
runs cleanly in a standalone Python process (the MCP server) or inside the FastAPI app.

Tools exposed
─────────────
  search_venues              Vector search over venue_master OpenSearch index
  recommend_venues           Ranked venue recommendations with scoring + LLM reasons
  find_nearby_venues         Relaxed fallback venue search (ignores city filter)
  search_event_requirements  Vector search over event_management OpenSearch index
  search_nearby_vendors      Vector search over vendor_intel + live scraping fallback
  scrape_vendors             Trigger live vendor scraping for a postcode
  extract_event_requirements LLM-based parsing of raw event brief text → structured JSON
  index_venues               Trigger incremental venue re-indexing from Canvas API
  opensearch_stats           Return doc counts and health for all 3 indices

Usage — standalone (MCP server)
───────────────────────────────
    from event_manager_tools import EventManagerProjectTools, EventManagerMcpConfig

    config = EventManagerMcpConfig.from_env()
    tools  = EventManagerProjectTools(config)
    result = tools.execute("search_venues", {"query": "Manchester conference room 200"})

Usage — in-app fallback (FastAPI)
──────────────────────────────────
    from app.tools.event_manager_mcp_tools import EventManagerProjectTools, EventManagerMcpConfig

    config = EventManagerMcpConfig.from_env()
    tools  = EventManagerProjectTools(config)
    result = tools.execute("recommend_venues", {
        "query": "wedding 120 guests London",
        "city": "London",
        "attendees": 120,
        "max_budget": 8000,
    })
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── Project identity ──────────────────────────────────────────────────────────

PROJECT_ID = "dstrmaysam-event-manager"

PROJECT_ALIASES = {
    "dstrmaysam-event-manager",
    "dstrmaysam_event_manager",
    "event_manager",
    "eventmanager",
    os.getenv("MCP_DEFAULT_PROJECT_ID", "dstrmaysam-event-manager"),
}

DEFAULT_MCP_SECRET_NAME = "/dstrmaysam-event-manager/mcp-tools"

# ── Environment helpers ────────────────────────────────────────────────────────


def mcp_runtime_env() -> str:
    return os.getenv("MCP_APP_ENV") or os.getenv("APP_ENV", "local")


def mcp_uses_local_resources() -> bool:
    local_test_admin_enabled = os.getenv("LOCAL_TEST_ADMIN_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return mcp_runtime_env().lower() in {"local", "test"} or local_test_admin_enabled


def hydrate_env_from_aws_secret(secret_name: str | None = None) -> dict[str, Any]:
    """Load environment variables from an AWS Secrets Manager JSON secret."""
    if mcp_uses_local_resources():
        return {"loaded": False, "reason": "local_mode", "keys": []}

    resolved = (
        secret_name
        or os.getenv("MCP_SECRET_NAME")
        or os.getenv("MCP_TOOLS_SECRET_NAME")
        or DEFAULT_MCP_SECRET_NAME
    )
    region = os.getenv("AWS_REGION", "eu-west-2")

    import boto3  # type: ignore

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=resolved)
    payload = json.loads((response.get("SecretString") or "{}").lstrip("﻿ï»¿"))
    if not isinstance(payload, dict):
        raise ValueError(f"MCP secret {resolved!r} must contain a JSON object")

    loaded_keys: list[str] = []
    skipped_keys: list[str] = []
    for key, value in payload.items():
        env_key = str(key).strip()
        if not env_key or not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_key) or value is None:
            skipped_keys.append(env_key)
            continue
        os.environ[env_key] = str(value)
        loaded_keys.append(env_key)

    return {
        "loaded": True,
        "secret_name": resolved,
        "keys": sorted(loaded_keys),
        "skipped_keys": sorted(k for k in skipped_keys if k),
    }


# ── Config ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EventManagerMcpConfig:
    """
    All configuration the event manager MCP tools need, read from environment variables.
    Use EventManagerMcpConfig.from_env() to build an instance.
    """
    app_env: str
    local_test_admin_enabled: bool
    aws_region: str

    # OpenSearch
    opensearch_endpoint: str
    opensearch_username: str
    opensearch_password: str
    opensearch_venue_index: str
    opensearch_event_index: str
    opensearch_vendor_index: str

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str
    azure_openai_deployment: str
    azure_openai_embedding_deployment: str

    # Canvas API (venue source)
    canvas_api_url: str
    canvas_api_key: str

    # Retrieval tuning
    rag_top_k: int
    embedding_cache_size: int

    # Vendor scraping
    vendor_radius_km: float

    @classmethod
    def from_env(cls) -> "EventManagerMcpConfig":
        return cls(
            app_env=os.getenv("MCP_APP_ENV") or os.getenv("APP_ENV", "local"),
            local_test_admin_enabled=os.getenv("LOCAL_TEST_ADMIN_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            aws_region=os.getenv("AWS_REGION", "eu-west-2"),
            opensearch_endpoint=os.getenv("OPENSEARCH_ENDPOINT", ""),
            opensearch_username=os.getenv("OPENSEARCH_USERNAME", "admin"),
            opensearch_password=os.getenv("OPENSEARCH_PASSWORD", ""),
            opensearch_venue_index=os.getenv("OPENSEARCH_VENUE_INDEX", "venue_master"),
            opensearch_event_index=os.getenv("OPENSEARCH_EVENT_INDEX", "event_management"),
            opensearch_vendor_index=os.getenv("OPENSEARCH_VENDOR_INDEX", "vendor_intel"),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"),
            azure_openai_embedding_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
            canvas_api_url=os.getenv("CANVAS_API_URL", ""),
            canvas_api_key=os.getenv("CANVAS_API_KEY", ""),
            rag_top_k=int(os.getenv("RAG_TOP_K", "10")),
            embedding_cache_size=int(os.getenv("RAG_EMBEDDING_CACHE_SIZE", "512")),
            vendor_radius_km=float(os.getenv("VENDOR_RADIUS_KM", "10.0")),
        )

    def use_local_resources(self) -> bool:
        return self.app_env.lower() in {"local", "test"} or self.local_test_admin_enabled


# ── OpenSearch client helpers ─────────────────────────────────────────────────


def _build_opensearch_client(config: EventManagerMcpConfig):
    """Build a raw opensearch-py client using HTTP basic auth."""
    from opensearchpy import OpenSearch, RequestsHttpConnection  # type: ignore

    endpoint = config.opensearch_endpoint.rstrip("/")
    host = re.sub(r"^https?://", "", endpoint)
    use_ssl = endpoint.startswith("https")
    return OpenSearch(
        hosts=[{"host": host, "port": 443 if use_ssl else 9200}],
        http_auth=(config.opensearch_username, config.opensearch_password),
        use_ssl=use_ssl,
        verify_certs=use_ssl,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def _format_venue_hits(hits: list[dict[str, Any]]) -> str:
    """Format raw OpenSearch venue hits into a human-readable string."""
    if not hits:
        return "No venues found."
    lines: list[str] = [f"Found {len(hits)} venue(s):\n"]
    for i, h in enumerate(hits, 1):
        m = h.get("metadata", {})
        lines.append(
            f"{i}. **{m.get('venue_name', 'Unknown')}** — {m.get('city', '')} {m.get('postcode', '')}\n"
            f"   Capacity: {m.get('capacity', '?')} | "
            f"Price: £{m.get('min_price', '?')}–£{m.get('max_price', '?')} | "
            f"Score: {h.get('score', '?')}\n"
            f"   {str(h.get('text', ''))[:300]}\n"
        )
    return "\n".join(lines)


def _format_vendor_hits(hits: list[dict[str, Any]]) -> str:
    """Format raw OpenSearch vendor hits into a human-readable string."""
    if not hits:
        return "No vendors found."
    lines: list[str] = [f"Found {len(hits)} vendor(s):\n"]
    for i, h in enumerate(hits, 1):
        m = h.get("metadata", {})
        dist = f"{float(m.get('distance_km', 0)):.1f} km" if m.get("distance_km") else ""
        price = f"£{float(m.get('price_per_head', 0)):.0f}/head" if m.get("price_per_head") else ""
        lines.append(
            f"{i}. **{m.get('name', 'Unknown')}** ({m.get('vendor_type', '').title()})"
            + (f" — {dist}" if dist else "")
            + (f" — {price}" if price else "") + "\n"
            f"   Phone: {m.get('phone', '—')} | Website: {m.get('website', '—')}\n"
            f"   {str(h.get('text', ''))[:250]}\n"
        )
    return "\n".join(lines)


# ── Main tools class ──────────────────────────────────────────────────────────


class EventManagerProjectTools:
    """
    Implements all Event Manager MCP tools.

    Works in two modes:
      - Standalone  (no app.*): uses direct OpenSearch + Azure OpenAI calls
      - App-assisted (app.* available): delegates to richer app-layer implementations

    The `execute()` method is the single entry point for the MCP server dispatcher.
    """

    def __init__(self, config: EventManagerMcpConfig):
        self.config = config
        self._os_client: Any | None = None
        self._embedding_model: Any | None = None
        self._embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._chat_client: Any | None = None

    # ── MCP dispatch ─────────────────────────────────────────────────────────

    def execute(self, tool_name: str, payload: dict[str, Any]) -> str:
        """
        Route a tool call from the MCP server to the correct method.

        payload keys (common):
          query          str  — natural-language search query
          city           str  — event city
          postcode       str  — UK postcode
          attendees      int  — expected guest count
          min_budget     float
          max_budget     float
          vendor_type    str  — "catering" | "hotel" | "" (both)
          event_id       str  — restrict vendor search to a specific event
          raw_text       str  — raw event brief text (for extract_event_requirements)
          event_type     str  — company_event | birthday | wedding | get_together
          relaxed        bool — find_nearby_venues: ignore city filter
        """
        query = str(payload.get("query") or "")

        dispatch: dict[str, Any] = {
            "search_venues":             lambda: self.search_venues(query, payload),
            "recommend_venues":          lambda: self.recommend_venues(query, payload),
            "find_nearby_venues":        lambda: self.find_nearby_venues(query, payload),
            "search_event_requirements": lambda: self.search_event_requirements(query, payload),
            "search_nearby_vendors":     lambda: self.search_nearby_vendors(query, payload),
            "scrape_vendors":            lambda: self.scrape_vendors(payload),
            "extract_event_requirements":lambda: self.extract_event_requirements(payload),
            "index_venues":              lambda: self.index_venues(payload),
            "opensearch_stats":          lambda: self.opensearch_stats(),
        }

        fn = dispatch.get(tool_name)
        if fn is None:
            return json.dumps({"error": f"Unknown tool: {tool_name!r}", "available": sorted(dispatch)})
        try:
            return fn()
        except Exception as exc:
            logger.error("Tool %r failed: %s", tool_name, exc)
            return json.dumps({"error": str(exc), "tool": tool_name})

    # ── Internal: OpenSearch ──────────────────────────────────────────────────

    def _os(self):
        if self._os_client is None:
            self._os_client = _build_opensearch_client(self.config)
        return self._os_client

    def _embed(self, text: str) -> list[float] | None:
        """Embed a query string using Azure OpenAI, with LRU cache."""
        if not self.config.azure_openai_endpoint or not self.config.azure_openai_api_key:
            return None
        cache_key = text.lower().strip()
        if cache_key in self._embedding_cache:
            vec = self._embedding_cache.pop(cache_key)
            self._embedding_cache[cache_key] = vec
            return vec
        try:
            from langchain_openai import AzureOpenAIEmbeddings  # type: ignore
            if self._embedding_model is None:
                self._embedding_model = AzureOpenAIEmbeddings(
                    azure_deployment=self.config.azure_openai_embedding_deployment,
                    azure_endpoint=self.config.azure_openai_endpoint,
                    api_key=self.config.azure_openai_api_key,
                    api_version=self.config.azure_openai_api_version,
                )
            vec = list(self._embedding_model.embed_query(text))
            self._embedding_cache[cache_key] = vec
            while len(self._embedding_cache) > self.config.embedding_cache_size:
                self._embedding_cache.popitem(last=False)
            return vec
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            return None

    def _vector_search(self, index: str, query: str, k: int, pre_filter: dict | None = None) -> list[dict]:
        """Run k-NN + BM25 hybrid search on an OpenSearch index."""
        results: list[dict] = []
        vector = self._embed(query)

        bodies: list[dict] = []
        if vector:
            knn_body: dict = {"size": k, "query": {"knn": {"embedding": {"vector": vector, "k": k}}}}
            if pre_filter:
                knn_body["post_filter"] = pre_filter
            bodies.append(knn_body)

        bm25_body: dict = {
            "size": k,
            "query": {"multi_match": {"query": query, "fields": ["text^2", "metadata.*"]}},
        }
        if pre_filter:
            bm25_body["post_filter"] = pre_filter
        bodies.append(bm25_body)

        seen: set[str] = set()
        for body in bodies:
            try:
                resp = self._os().search(index=index, body=body)
            except Exception as exc:
                logger.warning("OpenSearch query on %s failed: %s", index, exc)
                continue
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                uid = hit.get("_id", str(src.get("text", ""))[:60])
                if uid in seen:
                    continue
                seen.add(uid)
                results.append({
                    "text": src.get("text", ""),
                    "metadata": src.get("metadata", {}),
                    "score": hit.get("_score"),
                })
        return results[:k]

    def _chat_completion(self, system: str, user: str) -> str:
        """Single Azure OpenAI chat completion call."""
        if not self.config.azure_openai_endpoint or not self.config.azure_openai_api_key:
            return ""
        try:
            from openai import AzureOpenAI  # type: ignore
            if self._chat_client is None:
                self._chat_client = AzureOpenAI(
                    api_key=self.config.azure_openai_api_key,
                    azure_endpoint=self.config.azure_openai_endpoint,
                    api_version=self.config.azure_openai_api_version,
                )
            resp = self._chat_client.chat.completions.create(
                model=self.config.azure_openai_deployment,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0,
                max_tokens=1000,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("Chat completion failed: %s", exc)
            return ""

    # ── Tool 1: search_venues ─────────────────────────────────────────────────

    def search_venues(self, query: str, payload: dict[str, Any]) -> str:
        """
        Semantic search over the venue_master OpenSearch index.
        Returns up to rag_top_k venue chunks matching the query.

        Tries to delegate to app.tools.retrieval.retrieve_venues when in-app mode;
        falls back to direct OpenSearch query otherwise.
        """
        city: str = str(payload.get("city") or "").strip()
        k: int = int(payload.get("top_k") or self.config.rag_top_k)

        # ── Try app-layer (richer, uses vector store wrapper) ─────────────────
        try:
            from app.tools.retrieval import retrieve_venues  # type: ignore
            hits = retrieve_venues(query=query, city=city or None, top_k=k)
            return json.dumps({"results": hits, "count": len(hits), "source": "app_layer"})
        except ImportError:
            pass

        # ── Standalone: direct OpenSearch ─────────────────────────────────────
        pre_filter = None
        if city:
            pre_filter = {"term": {"metadata.city.keyword": city}}

        hits = self._vector_search(self.config.opensearch_venue_index, query, k, pre_filter)
        return json.dumps({"results": hits, "count": len(hits), "source": "opensearch_direct",
                           "formatted": _format_venue_hits(hits)})

    # ── Tool 2: recommend_venues ──────────────────────────────────────────────

    def recommend_venues(self, query: str, payload: dict[str, Any]) -> str:
        """
        Full venue recommendation pipeline: retrieve → rank → LLM reasons.
        Delegates to app.agent.tools.recommendation_tool when available.

        payload: city, attendees, min_budget, max_budget, event_date,
                 additional_requirements (comma-separated str)
        """
        city       = str(payload.get("city") or "")
        attendees  = int(payload.get("attendees") or 0)
        min_budget = float(payload.get("min_budget") or 0)
        max_budget = float(payload.get("max_budget") or 0)
        event_date = str(payload.get("event_date") or "")
        add_reqs   = str(payload.get("additional_requirements") or "")

        # ── Try app-layer ─────────────────────────────────────────────────────
        try:
            from app.agent.tools.recommendation_tool import _recommend_fn  # type: ignore
            return _recommend_fn(
                city=city, attendees=attendees, min_budget=min_budget,
                max_budget=max_budget, event_date=event_date,
                additional_requirements=add_reqs,
            )
        except ImportError:
            pass

        # ── Standalone: retrieve + simple score + LLM reasons ─────────────────
        search_q = " ".join(filter(None, [
            "event venue", city, f"{attendees} guests" if attendees else "",
            f"budget {max_budget}" if max_budget else "", add_reqs,
        ]))
        hits = self._vector_search(self.config.opensearch_venue_index, search_q,
                                   self.config.rag_top_k * 2)

        # Apply simple city hard-filter and capacity/budget score
        def _score(h: dict) -> float:
            m = h.get("metadata", {})
            s = float(h.get("score") or 0) * 10
            if city and str(m.get("city", "")).lower() != city.lower():
                return -1.0
            cap = int(m.get("capacity") or 0)
            if attendees and cap and cap >= attendees:
                s += 30
            min_p = float(m.get("min_price") or 0)
            if max_budget and min_p <= max_budget:
                s += 20
            return s

        ranked = sorted(hits, key=_score, reverse=True)
        ranked = [r for r in ranked if _score(r) >= 0][:10]

        # LLM reasons (best-effort)
        reasons: list[str] = []
        if ranked:
            venue_lines = "\n".join(
                f"{i+1}. {r['metadata'].get('venue_name','?')} ({r['metadata'].get('city','')}): "
                f"cap {r['metadata'].get('capacity','?')}, "
                f"£{r['metadata'].get('min_price','?')}–£{r['metadata'].get('max_price','?')}"
                for i, r in enumerate(ranked[:5])
            )
            raw = self._chat_completion(
                "Return JSON {\"reasons\":[...]} with a 2-sentence reason per venue. Use only the data provided.",
                f"Event: {attendees} guests in {city or 'UK'}, budget £{min_budget:,.0f}–£{max_budget:,.0f}\n"
                f"Requirements: {add_reqs}\n\nVenues:\n{venue_lines}"
            )
            try:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                reasons = json.loads(m.group(0)).get("reasons", []) if m else []
            except Exception:
                pass

        venues_out = []
        for i, r in enumerate(ranked):
            meta = r.get("metadata", {})
            reason = reasons[i] if i < len(reasons) else (
                f"This venue in {meta.get('city','?')} accommodates up to {meta.get('capacity','?')} guests.")
            venues_out.append({
                "venue_name": meta.get("venue_name", "Unknown"),
                "city": meta.get("city", ""),
                "postcode": meta.get("postcode", ""),
                "capacity": meta.get("capacity", "?"),
                "min_price": meta.get("min_price"),
                "max_price": meta.get("max_price"),
                "venue_url": meta.get("venue_url", ""),
                "match_score": round(max(0, _score(r)), 1),
                "recommendation_reason": reason,
                "features": meta.get("features", ""),
                "parking": meta.get("parking"),
                "wifi": meta.get("wifi"),
                "av_equipment": meta.get("av_equipment"),
                "outdoor_space": meta.get("outdoor_space"),
                "catering": meta.get("catering"),
            })

        best = venues_out[0]["venue_name"] if venues_out else "No venues found"
        return json.dumps({
            "venues": venues_out,
            "summary": {
                "total_venues": len(venues_out),
                "best_venue": best,
                "budget_analysis": f"{sum(1 for v in venues_out if float(v.get('min_price') or 0) <= max_budget)} within budget" if max_budget else "budget not specified",
            },
            "source": "opensearch_direct",
        })

    # ── Tool 3: find_nearby_venues ────────────────────────────────────────────

    def find_nearby_venues(self, query: str, payload: dict[str, Any]) -> str:
        """
        Relaxed venue search — ignores city hard-filter, returns broader results.
        Used as fallback when recommend_venues returns 0 results or low scores.
        """
        # ── Try app-layer ─────────────────────────────────────────────────────
        try:
            from app.agent.tools.nearby_venue_tool import _find_nearby_fn  # type: ignore
            return _find_nearby_fn(query=query, relaxed=True)
        except ImportError:
            pass

        # ── Standalone: wider search, no city filter ──────────────────────────
        k = int(payload.get("top_k") or self.config.rag_top_k)
        hits = self._vector_search(self.config.opensearch_venue_index, query, k)
        return json.dumps({"results": hits, "count": len(hits), "relaxed": True,
                           "source": "opensearch_direct",
                           "formatted": _format_venue_hits(hits)})

    # ── Tool 4: search_event_requirements ────────────────────────────────────

    def search_event_requirements(self, query: str, payload: dict[str, Any]) -> str:
        """
        Semantic search over the event_management OpenSearch index (uploaded event briefs).
        Returns matching chunks from previously uploaded event documents.
        """
        collection = str(payload.get("collection_name") or "")
        k = int(payload.get("top_k") or self.config.rag_top_k)

        # ── Try app-layer ─────────────────────────────────────────────────────
        try:
            from app.tools.event_storage import retrieve_event_requirements  # type: ignore
            hits = retrieve_event_requirements(query=query, collection_name=collection, top_k=k)
            return json.dumps({"results": hits, "count": len(hits), "source": "app_layer"})
        except ImportError:
            pass

        # ── Standalone: direct OpenSearch ─────────────────────────────────────
        pre_filter = None
        if collection:
            pre_filter = {"term": {"metadata.collection_name.keyword": collection}}
        hits = self._vector_search(self.config.opensearch_event_index, query, k, pre_filter)
        return json.dumps({"results": hits, "count": len(hits), "source": "opensearch_direct"})

    # ── Tool 5: search_nearby_vendors ────────────────────────────────────────

    def search_nearby_vendors(self, query: str, payload: dict[str, Any]) -> str:
        """
        Search the vendor_intel OpenSearch index for caterers and hotels.
        If the index is empty and a UK postcode appears in the query, triggers
        a live scrape (app-layer only) then retries.

        payload: vendor_type ("catering"|"hotel"|""), event_id, postcode
        """
        vendor_type = str(payload.get("vendor_type") or "")
        event_id    = str(payload.get("event_id") or "")
        postcode    = str(payload.get("postcode") or "")
        k = int(payload.get("top_k") or self.config.rag_top_k)

        # Enrich query with postcode if known
        full_query = query
        if postcode and postcode not in query:
            full_query = f"{query} near {postcode}"

        # ── Try app-layer (includes live-scraping fallback) ───────────────────
        try:
            from app.modules.vendors.vendor_indexer import search_vendor_intel  # type: ignore
            pre_filter = None
            if vendor_type and event_id:
                pre_filter = {"bool": {"must": [
                    {"term": {"metadata.vendor_type.keyword": vendor_type}},
                    {"term": {"metadata.event_id.keyword": event_id}},
                ]}}
            elif vendor_type:
                pre_filter = {"term": {"metadata.vendor_type.keyword": vendor_type}}
            elif event_id:
                pre_filter = {"term": {"metadata.event_id.keyword": event_id}}

            results = search_vendor_intel(full_query, vendor_type or None, event_id or None, k=k)

            # Live scrape fallback when index is empty for this area
            if not results and postcode:
                _post = str(postcode).strip().upper()
                logger.info("vendor_intel empty — triggering live scrape for %s", _post)
                self._try_live_scrape(postcode=_post, city=str(payload.get("city") or ""),
                                      attendees=int(payload.get("attendees") or 0),
                                      total_budget=float(payload.get("max_budget") or 0))
                results = search_vendor_intel(full_query, vendor_type or None, event_id or None, k=k)

            return json.dumps({"results": results, "count": len(results), "source": "app_layer",
                               "formatted": _format_vendor_hits(results)})
        except ImportError:
            pass

        # ── Standalone: direct OpenSearch ─────────────────────────────────────
        pre_filter = None
        if vendor_type:
            pre_filter = {"term": {"metadata.vendor_type.keyword": vendor_type}}
        hits = self._vector_search(self.config.opensearch_vendor_index, full_query, k, pre_filter)
        return json.dumps({"results": hits, "count": len(hits), "source": "opensearch_direct",
                           "formatted": _format_vendor_hits(hits)})

    # ── Tool 6: scrape_vendors ────────────────────────────────────────────────

    def scrape_vendors(self, payload: dict[str, Any]) -> str:
        """
        Trigger a live vendor scrape for a postcode and index results into vendor_intel.

        payload: postcode (required), city, attendees, max_budget,
                 food_required (bool), hotel_required (bool), radius_km
        """
        postcode = str(payload.get("postcode") or "").strip()
        if not postcode:
            return json.dumps({"error": "postcode is required for vendor scraping"})

        city          = str(payload.get("city") or "")
        attendees     = int(payload.get("attendees") or 0)
        total_budget  = float(payload.get("max_budget") or 0)
        food_required = bool(payload.get("food_required", True))
        hotel_required = bool(payload.get("hotel_required", True))
        radius_km     = float(payload.get("radius_km") or self.config.vendor_radius_km)
        food_categories = list(payload.get("food_categories") or [])

        indexed = self._try_live_scrape(
            postcode=postcode, city=city, attendees=attendees,
            total_budget=total_budget, food_required=food_required,
            hotel_required=hotel_required, radius_km=radius_km,
            food_categories=food_categories,
        )
        return json.dumps({"indexed": indexed, "postcode": postcode, "city": city})

    def _try_live_scrape(
        self,
        postcode: str,
        city: str = "",
        attendees: int = 0,
        total_budget: float = 0.0,
        food_required: bool = True,
        hotel_required: bool = True,
        radius_km: float = 10.0,
        food_categories: list[str] | None = None,
    ) -> int:
        """App-layer live scrape; returns count indexed (0 in standalone mode)."""
        try:
            from app.modules.vendors.smart_scraper import EventScraperConfig, run_event_scrape  # type: ignore
            from app.modules.vendors.vendor_pipeline import run_pipeline  # type: ignore
            from app.modules.vendors.vendor_indexer import index_vendors  # type: ignore

            config = EventScraperConfig(
                postcode=postcode, city=city, attendees=attendees,
                total_budget=total_budget, food_required=food_required,
                hotel_required=hotel_required,
                food_categories=list(food_categories or []),
                radius_km=radius_km,
            )
            raw     = run_event_scrape(config)
            cleaned = run_pipeline(raw, config)
            result  = index_vendors(cleaned)
            return int(result.get("indexed", 0))
        except ImportError:
            logger.info("App-layer vendor scraping not available in standalone mode")
            return 0
        except Exception as exc:
            logger.warning("Live vendor scrape failed for %s: %s", postcode, exc)
            return 0

    # ── Tool 7: extract_event_requirements ───────────────────────────────────

    def extract_event_requirements(self, payload: dict[str, Any]) -> str:
        """
        Parse raw event brief text and return structured EventRequirements JSON.

        payload: raw_text (str), event_type (str)
        """
        raw_text   = str(payload.get("raw_text") or payload.get("query") or "")
        event_type = str(payload.get("event_type") or "company_event")

        if not raw_text:
            return json.dumps({"error": "raw_text is required"})

        # ── Try app-layer (uses full ExtractionAgent) ─────────────────────────
        try:
            from app.agent.event_agent import process_event_requirements  # type: ignore
            result = process_event_requirements(raw_text, event_type, venue_required=False)
            reqs   = result.get("event_requirements")
            if reqs:
                d = reqs.model_dump() if hasattr(reqs, "model_dump") else (reqs.dict() if hasattr(reqs, "dict") else reqs)
                return json.dumps({"requirements": d, "source": "app_layer"}, default=str)
        except ImportError:
            pass

        # ── Standalone: direct LLM extraction ────────────────────────────────
        schema = (
            "Return ONLY valid JSON matching this schema (no other text):\n"
            '{"event_type":"company_event|birthday|wedding|get_together","event_date":"","event_time":"","city":"",'
            '"postcode":"","attendees":0,"min_budget":0,"max_budget":0,"food_required":true,"food_categories":[],'
            '"hotel_required":false,"additional_requirements":[]}'
        )
        raw_json = self._chat_completion(
            f"You extract structured event requirements from text. {schema}",
            f"Event brief:\n{raw_text[:3000]}"
        )
        try:
            m = re.search(r"\{.*\}", raw_json, re.DOTALL)
            reqs = json.loads(m.group(0)) if m else {}
        except Exception:
            reqs = {}

        return json.dumps({"requirements": reqs, "source": "llm_direct"}, default=str)

    # ── Tool 8: index_venues ──────────────────────────────────────────────────

    def index_venues(self, payload: dict[str, Any]) -> str:
        """
        Trigger incremental venue re-indexing from the Canvas Venues API.
        Only meaningful in app-layer mode (requires Canvas API credentials).

        payload: full_reindex (bool, default False)
        """
        full = bool(payload.get("full_reindex", False))

        try:
            from app.services.indexing_service import run_incremental_indexing, run_full_reindex  # type: ignore
            if full:
                result = run_full_reindex()
            else:
                result = run_incremental_indexing()
            return json.dumps({"status": "ok", "result": result, "full_reindex": full, "source": "app_layer"})
        except ImportError:
            return json.dumps({"status": "unavailable",
                               "reason": "index_venues requires the app layer (not available in standalone MCP mode)",
                               "full_reindex": full})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

    # ── Tool 9: opensearch_stats ──────────────────────────────────────────────

    def opensearch_stats(self) -> str:
        """
        Return document counts and index health for all 3 OpenSearch indices.
        Works in both standalone and app-layer mode.
        """
        indices = {
            "venue_master": self.config.opensearch_venue_index,
            "event_management": self.config.opensearch_event_index,
            "vendor_intel": self.config.opensearch_vendor_index,
        }
        stats: dict[str, Any] = {}

        # ── Try app-layer count helpers first ─────────────────────────────────
        try:
            from app.tools.opensearch_client import index_count  # type: ignore
            for label, idx in indices.items():
                try:
                    stats[label] = {"index": idx, "doc_count": index_count(idx)}
                except Exception as exc:
                    stats[label] = {"index": idx, "error": str(exc)}
            return json.dumps({"indices": stats, "source": "app_layer"})
        except ImportError:
            pass

        # ── Standalone: direct OpenSearch ─────────────────────────────────────
        for label, idx in indices.items():
            try:
                resp = self._os().count(index=idx)
                stats[label] = {"index": idx, "doc_count": resp.get("count", 0)}
            except Exception as exc:
                stats[label] = {"index": idx, "error": str(exc)}

        return json.dumps({"indices": stats, "source": "opensearch_direct"})


# ── MCP server tool definitions ───────────────────────────────────────────────
# Each entry is a dict that the MCP dispatcher can consume directly.

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_venues",
        "description": (
            "Semantic search over the venue_master OpenSearch index. "
            "Returns venue chunks matching the query (name, city, description, features). "
            "Use for free-text venue discovery."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":   {"type": "string", "description": "Natural-language venue search query"},
                "city":    {"type": "string", "description": "Optional city filter (e.g. 'Manchester')"},
                "top_k":   {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recommend_venues",
        "description": (
            "Full venue recommendation pipeline: retrieve from OpenSearch, score using "
            "capacity/budget/location/features weights, generate LLM reasoning, return ranked list. "
            "Use this in the main upload flow after extracting requirements."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":                   {"type": "string"},
                "city":                    {"type": "string"},
                "attendees":               {"type": "integer"},
                "min_budget":              {"type": "number"},
                "max_budget":              {"type": "number"},
                "event_date":              {"type": "string"},
                "additional_requirements": {"type": "string", "description": "Comma-separated requirements"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_nearby_venues",
        "description": (
            "Relaxed venue search that ignores the city hard-filter. "
            "Use as fallback when recommend_venues returns 0 results or all scores < 40."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":  {"type": "string"},
                "top_k":  {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_event_requirements",
        "description": (
            "Semantic search over uploaded event briefs in the event_management OpenSearch index. "
            "Use when the chat agent needs to recall a user's previously uploaded event requirements."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":           {"type": "string"},
                "collection_name": {"type": "string", "description": "Optional — restrict to a specific event collection"},
                "top_k":           {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_nearby_vendors",
        "description": (
            "Search the vendor_intel OpenSearch index for local caterers and hotels. "
            "Always include the full UK postcode in the query so the system can find local vendors. "
            "Automatically triggers a live scrape when the index is empty for the given postcode."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string", "description": "Include the UK postcode (e.g. 'caterers near LS1 4BR')"},
                "vendor_type": {"type": "string", "description": "'catering' | 'hotel' | '' (both)"},
                "event_id":    {"type": "string"},
                "postcode":    {"type": "string"},
                "city":        {"type": "string"},
                "attendees":   {"type": "integer"},
                "max_budget":  {"type": "number"},
                "top_k":       {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "scrape_vendors",
        "description": (
            "Trigger a live vendor scrape for a UK postcode using OSM Overpass, FSA API, "
            "DuckDuckGo, and Yell.com. Indexes results into vendor_intel. "
            "Use before search_nearby_vendors when you know the index is empty for this area."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "postcode":        {"type": "string"},
                "city":            {"type": "string"},
                "attendees":       {"type": "integer"},
                "max_budget":      {"type": "number"},
                "food_required":   {"type": "boolean"},
                "hotel_required":  {"type": "boolean"},
                "radius_km":       {"type": "number"},
                "food_categories": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["postcode"],
        },
    },
    {
        "name": "extract_event_requirements",
        "description": (
            "Parse raw event brief text (from PDF/DOCX/CSV upload or plain text) into a structured "
            "EventRequirements JSON object containing event_type, city, postcode, attendees, budget, "
            "food_categories, hotel_required, additional_requirements, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_text":   {"type": "string", "description": "The full text of the event brief"},
                "event_type": {"type": "string", "description": "company_event | birthday | wedding | get_together"},
            },
            "required": ["raw_text"],
        },
    },
    {
        "name": "index_venues",
        "description": (
            "Trigger incremental (or full) venue re-indexing from the Canvas Venues API into venue_master. "
            "Only available when running inside the FastAPI app (not in standalone MCP mode)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "full_reindex": {"type": "boolean", "description": "True = wipe and rebuild; False = incremental"},
            },
        },
    },
    {
        "name": "opensearch_stats",
        "description": "Return document counts and health for all 3 OpenSearch indices (venue_master, event_management, vendor_intel).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return the MCP tool definitions list (for the MCP server to register)."""
    return TOOL_DEFINITIONS


def get_project_tools(config: EventManagerMcpConfig | None = None) -> EventManagerProjectTools:
    """Convenience factory — builds tools from env if no config provided."""
    return EventManagerProjectTools(config or EventManagerMcpConfig.from_env())


# ── Standalone entrypoint (used by MCP server) ────────────────────────────────

if __name__ == "__main__":
    import sys
    cfg   = EventManagerMcpConfig.from_env()
    tools = EventManagerProjectTools(cfg)

    tool_name = sys.argv[1] if len(sys.argv) > 1 else "opensearch_stats"
    payload   = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(tools.execute(tool_name, payload))
