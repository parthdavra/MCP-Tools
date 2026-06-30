from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_local_core_src = (
    Path(__file__).resolve().parents[3]
    / "dstrmaysam-heakthcare-knowledge-agent-multi-agent"
    / "backend"
    / "packages"
    / "healthcare_tools_core"
    / "src"
)
if _local_core_src.exists() and str(_local_core_src) not in sys.path:
    sys.path.insert(0, str(_local_core_src))

from healthcare_tools_core import (
    DeterministicLookupService,
    user_context_from_payload,
)

STOPWORDS = {
    "a",
    "all",
    "any",
    "anybody",
    "anyone",
    "are",
    "be",
    "does",
    "for",
    "from",
    "have",
    "how",
    "in",
    "info",
    "information",
    "is",
    "list",
    "many",
    "me",
    "of",
    "on",
    "show",
    "tell",
    "the",
    "there",
    "to",
    "we",
    "what",
    "which",
    "who",
}

DEFAULT_MCP_SECRET_NAME = "/dstrmaysam-healthcare-knowledge-multi-agent-dev/mcp-tools"


def mcp_runtime_env() -> str:
    return os.getenv("MCP_APP_ENV") or os.getenv("APP_ENV", "local")


def mcp_uses_local_resources() -> bool:
    local_test_admin_enabled = os.getenv("LOCAL_TEST_ADMIN_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return mcp_runtime_env().lower() in {"local", "test"} or local_test_admin_enabled


def hydrate_env_from_aws_secret(secret_name: str | None = None) -> dict[str, Any]:
    if mcp_uses_local_resources():
        return {"loaded": False, "reason": "local_mode", "keys": []}

    resolved_secret_name = (
        secret_name
        or os.getenv("MCP_SECRET_NAME")
        or os.getenv("MCP_TOOLS_SECRET_NAME")
        or DEFAULT_MCP_SECRET_NAME
    )
    region = os.getenv("AWS_REGION", "eu-west-2")

    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=resolved_secret_name)
    payload = json.loads((response.get("SecretString") or "{}").lstrip("\ufeffï»¿"))
    if not isinstance(payload, dict):
        raise ValueError(f"MCP secret {resolved_secret_name!r} must contain a JSON object")

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
        "secret_name": resolved_secret_name,
        "keys": sorted(loaded_keys),
        "skipped_keys": sorted(key for key in skipped_keys if key),
    }


CRM_TABLES: dict[str, dict[str, Any]] = {
    "patients": {
        "table": "patients",
        "pk": "patient_id",
        "columns": ["patient_id", "mrn", "nhs_number", "full_name", "date_of_birth", "ward_code", "department_id", "department_name", "named_consultant", "care_status", "risk_flags", "access_level"],
        "search": ["patient_id", "mrn", "nhs_number", "full_name", "department_name", "named_consultant", "care_status", "risk_flags"],
    },
    "doctors": {
        "table": "doctors",
        "pk": "doctor_id",
        "columns": ["doctor_id", "full_name", "grade", "specialty", "department_id", "department_name", "phone", "email", "bleep", "on_call_today", "access_level"],
        "search": ["doctor_id", "full_name", "grade", "specialty", "department_name", "phone", "email", "bleep"],
    },
    "departments": {
        "table": "departments",
        "pk": "department_id",
        "columns": ["department_id", "department_name", "specialty_group", "location", "main_phone", "email", "service_lead", "escalation_contact", "access_level"],
        "search": ["department_id", "department_name", "specialty_group", "location", "main_phone", "email", "service_lead", "escalation_contact"],
    },
    "schedule": {
        "table": "staff_schedule",
        "pk": "schedule_id",
        "columns": ["schedule_id", "shift_date", "department_id", "department_name", "role", "staff_name", "shift_start", "shift_end", "on_call", "contact", "access_level"],
        "search": ["schedule_id", "department_name", "role", "staff_name", "contact"],
    },
    "appointments": {
        "table": "appointments",
        "pk": "appointment_id",
        "columns": ["appointment_id", "patient_mrn", "patient_name", "clinic_name", "department_id", "department_name", "appointment_date", "appointment_time", "clinician_name", "status", "referral_priority", "access_level"],
        "search": ["appointment_id", "patient_mrn", "patient_name", "clinic_name", "department_name", "clinician_name", "status", "referral_priority"],
    },
    "wards": {
        "table": "wards",
        "pk": "ward_code",
        "columns": ["ward_code", "ward_name", "department_id", "department_name", "floor", "bed_capacity", "beds_available", "nurse_in_charge", "phone", "access_level"],
        "search": ["ward_code", "ward_name", "department_name", "floor", "nurse_in_charge", "phone"],
    },
    "contacts": {
        "table": "organization_contacts",
        "pk": "contact_id",
        "columns": ["contact_id", "contact_type", "department_id", "department_name", "contact_name", "role", "phone", "email", "available_hours", "escalation_level", "access_level"],
        "search": ["contact_id", "contact_type", "department_name", "contact_name", "role", "phone", "email", "available_hours"],
    },
    "formulary": {
        "table": "formulary",
        "pk": "medicine_id",
        "columns": ["medicine_id", "medicine_name", "category", "restricted", "approval_required", "max_adult_dose", "monitoring_required", "access_level"],
        "search": ["medicine_id", "medicine_name", "category", "approval_required", "max_adult_dose", "monitoring_required"],
    },
    "clinic_sessions": {
        "table": "clinic_sessions",
        "pk": "clinic_id",
        "columns": ["clinic_id", "clinic_name", "clinic_date", "start_time", "consultant", "slots_total", "slots_available", "referral_priority", "access_level"],
        "search": ["clinic_id", "clinic_name", "consultant", "referral_priority"],
    },
    "equipment": {
        "table": "equipment_assets",
        "pk": "asset_id",
        "columns": ["asset_id", "equipment_type", "location", "status", "last_service_date", "next_service_due", "clinical_engineering_contact", "access_level"],
        "search": ["asset_id", "equipment_type", "location", "status", "clinical_engineering_contact"],
    },
    "finance": {
        "table": "finance_records",
        "pk": "finance_id",
        "columns": ["finance_id", "patient_mrn", "patient_name", "department_id", "department_name", "account_type", "payer_type", "amount_due", "amount_paid", "balance", "invoice_status", "last_invoice_date", "access_level"],
        "search": ["finance_id", "patient_mrn", "patient_name", "department_name", "account_type", "payer_type", "invoice_status"],
    },
    "compliance_audits": {
        "table": "compliance_audits",
        "pk": "audit_id",
        "columns": ["audit_id", "department_id", "department_name", "topic", "lead", "due_date", "status", "last_score_percent", "access_level"],
        "search": ["audit_id", "department_name", "topic", "lead", "status"],
    },
    "training": {
        "table": "training_records",
        "pk": "training_id",
        "columns": ["training_id", "staff_name", "role", "department_id", "department_name", "training_module", "completion_date", "expiry_date", "status", "access_level"],
        "search": ["training_id", "staff_name", "role", "department_name", "training_module", "status"],
    },
}


@dataclass(frozen=True)
class HealthcareMcpConfig:
    app_env: str
    local_test_admin_enabled: bool
    aws_region: str
    local_data_dir: str
    manifest_key: str
    s3_bucket: str
    s3_raw_prefix: str
    opensearch_endpoint: str
    opensearch_index: str
    azure_openai_secret_name: str
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str
    azure_openai_embedding_deployment: str
    rag_top_k: int
    rag_neighbor_chunks: int
    rag_embedding_cache_size: int
    document_manifest_cache_ttl_seconds: int
    deterministic_lookup_enabled: bool
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_sslmode: str

    @classmethod
    def from_env(cls) -> "HealthcareMcpConfig":
        return cls(
            app_env=os.getenv("MCP_APP_ENV") or os.getenv("APP_ENV", "local"),
            local_test_admin_enabled=os.getenv("LOCAL_TEST_ADMIN_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            aws_region=os.getenv("AWS_REGION", "eu-west-2"),
            local_data_dir=os.getenv("HEALTHCARE_LOCAL_DATA_DIR") or os.getenv("LOCAL_DATA_DIR", "/app/data"),
            manifest_key=os.getenv("HEALTHCARE_MANIFEST_KEY") or os.getenv("S3_MANIFEST_KEY", "manifests/documents.json"),
            s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_raw_prefix=os.getenv("S3_RAW_PREFIX", "raw/"),
            opensearch_endpoint=os.getenv("OPENSEARCH_ENDPOINT", ""),
            opensearch_index=os.getenv("OPENSEARCH_INDEX", "dstrmaysam-healthcare-knowledge-multi-agent-dev"),
            azure_openai_secret_name=os.getenv(
                "AZURE_OPENAI_SECRET_NAME",
                "/dstrmaysam-healthcare-knowledge-multi-agent-dev/azure-openai",
            ),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_openai_embedding_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""),
            rag_top_k=int(os.getenv("RAG_TOP_K", "10")),
            rag_neighbor_chunks=int(os.getenv("RAG_NEIGHBOR_CHUNKS", "1")),
            rag_embedding_cache_size=int(os.getenv("RAG_EMBEDDING_CACHE_SIZE", "512")),
            document_manifest_cache_ttl_seconds=int(os.getenv("DOCUMENT_MANIFEST_CACHE_TTL_SECONDS", "300")),
            deterministic_lookup_enabled=os.getenv("DETERMINISTIC_LOOKUP_ENABLED", "true").strip().lower()
            in {"1", "true", "yes", "on"},
            postgres_host=os.getenv("POSTGRES_HOST", "host.docker.internal"),
            postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
            postgres_db=os.getenv("POSTGRES_DB", "healthcare_agent"),
            postgres_user=os.getenv("POSTGRES_USER", "healthcare_agent"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", "healthcare_agent_dev"),
            postgres_sslmode=os.getenv("POSTGRES_SSLMODE", "disable"),
        )

    def use_local_resources(self) -> bool:
        return self.app_env.lower() in {"local", "test"} or self.local_test_admin_enabled


def _terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9_@.+-]+", query.lower()) if term and term not in STOPWORDS]


def _like(term: str) -> str:
    return f"%{term.lower()}%"


def _access_scopes(user_context: dict[str, Any]) -> tuple[str, ...]:
    roles = {str(role).lower() for role in user_context.get("roles") or ["staff"]}
    scopes = {"all_staff"}
    if roles & {"admin", "director"}:
        return ("all_staff", "clinical", "pharmacy", "manager", "hr_manager", "ig_manager", "director")
    if roles & {"doctor", "physician", "nurse", "clinical", "clinician"}:
        scopes.add("clinical")
    if roles & {"pharmacist", "pharmacy"}:
        scopes.update({"clinical", "pharmacy"})
    if roles & {"manager", "department_manager"}:
        scopes.update({"clinical", "manager"})
    if roles & {"hr", "hr_manager"}:
        scopes.add("hr_manager")
    return tuple(sorted(scopes))


def _allowed_roles(metadata: dict[str, Any]) -> set[str]:
    allowed = metadata.get("allowed_roles") or metadata.get("roles") or ["staff"]
    if isinstance(allowed, str):
        allowed = [allowed]
    return {str(role).lower() for role in allowed}


def _can_access_metadata(user_context: dict[str, Any], metadata: dict[str, Any]) -> bool:
    roles = {str(role).lower() for role in user_context.get("roles") or ["staff"]}
    if "admin" in roles:
        return True
    return bool(roles & _allowed_roles(metadata))


def _metadata_is_policy(metadata: dict[str, Any], title: str = "") -> bool:
    domain = str(metadata.get("domain") or "").lower()
    document_type = str(metadata.get("document_type") or "").lower()
    return (
        domain in {"clinical_policy", "admin_policy", "compliance"}
        or document_type in {"policy", "sop", "pathway", "guideline"}
        or "policy" in title.lower()
    )


def _format_retrieval_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "No relevant document chunks found."
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        details = {
            key: value
            for key, value in {
                "chunk_index": metadata.get("_chunk_index") or metadata.get("chunk_index"),
                "domain": metadata.get("domain"),
                "document_type": metadata.get("document_type"),
            }.items()
            if value not in (None, "", {})
        }
        detail_text = f"\nMetadata: {json.dumps(details, sort_keys=True)}" if details else ""
        lines.append(
            f"[{index}] {hit.get('title') or hit.get('key') or 'Untitled'} "
            f"({hit.get('uri') or ''}, score={hit.get('score')}){detail_text}\n"
            f"{str(hit.get('text') or '')[:1200]}"
        )
    return "\n\n".join(lines)


def _safety_assessment(query: str, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized = query.lower()
    urgent_terms = (
        "chest pain",
        "stroke",
        "sepsis",
        "suicide",
        "self harm",
        "anaphylaxis",
        "cardiac arrest",
        "unconscious",
        "not breathing",
        "overdose",
        "safeguarding",
    )
    patient_terms = (
        "patient",
        "diagnose",
        "treat",
        "prescribe",
        "dosage",
        "symptoms",
        "lab result",
        "blood pressure",
    )
    flags: list[str] = []
    escalation_required = False
    allow_answer = True
    if any(term in normalized for term in urgent_terms):
        flags.append("urgent_or_high_risk_clinical_term")
        escalation_required = True
    if any(term in normalized for term in patient_terms):
        flags.append("patient_specific_or_clinical_advice")
    if not sources:
        flags.append("missing_cited_sources")
        if "patient_specific_or_clinical_advice" in flags or "urgent_or_high_risk_clinical_term" in flags:
            allow_answer = False
    if escalation_required:
        message = (
            "Potential urgent or high-risk healthcare request. Provide approved policy "
            "citations only and direct the user to local escalation pathways."
        )
    elif not allow_answer:
        message = "Clinical or patient-specific request lacks cited approved sources."
    elif flags:
        message = "Safety guard detected issues that should be reflected in the final answer."
    else:
        message = "No safety issues detected."
    return {
        "risk_level": "high" if escalation_required else "medium" if flags else "low",
        "flags": flags,
        "escalation_required": escalation_required,
        "allow_answer": allow_answer,
        "message": message,
    }


def _category(query: str, tool_name: str = "") -> str:
    q = query.lower()
    if tool_name in {"calendar_rota_lookup"} or any(marker in q for marker in ["on call", "on-call", "oncall", "rota"]):
        return "schedule"
    if any(marker in q for marker in ["appointment", "clinic", "referral"]):
        return "appointments"
    if any(marker in q for marker in ["patient", "mrn", "nhs", "dob"]):
        return "patients"
    if any(marker in q for marker in ["doctor", "physician", "consultant", "clinician"]):
        return "doctors"
    if any(marker in q for marker in ["department", "service", "unit"]):
        return "departments"
    if any(marker in q for marker in ["contact", "phone", "email", "bleep", "extension"]):
        return "contacts"
    if any(marker in q for marker in ["ward", "bed", "floor"]):
        return "wards"
    if tool_name == "formulary_table_lookup" or any(marker in q for marker in ["medicine", "drug", "formulary", "dose", "restricted"]):
        return "formulary"
    if any(marker in q for marker in ["equipment", "asset", "device", "ventilator", "defibrillator", "pump", "monitor", "machine"]):
        return "equipment"
    if any(marker in q for marker in ["finance", "invoice", "balance", "payer"]):
        return "finance"
    if any(marker in q for marker in ["audit", "compliance"]):
        return "compliance_audits"
    if any(marker in q for marker in ["training", "competency"]):
        return "training"
    return "departments"


def _requested_dates(query: str) -> list[str]:
    q = query.lower()
    today = date.today()
    dates: list[date] = []
    if "today" in q:
        dates.append(today)
    if "tomorrow" in q:
        dates.append(today + timedelta(days=1))
    week_start = today - timedelta(days=today.weekday())
    if "next week" in q:
        dates.extend(week_start + timedelta(days=offset) for offset in range(7, 14))
    for match in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", query):
        try:
            dates.append(date.fromisoformat(match))
        except ValueError:
            pass
    seen: list[str] = []
    for value in dates:
        iso = value.isoformat()
        if iso not in seen:
            seen.append(iso)
    return seen


class HealthcareProjectTools:
    def __init__(self, config: HealthcareMcpConfig):
        self.config = config
        self._manifest_cache: dict[str, Any] | None = None
        self._manifest_cache_expires_at = 0.0
        self._s3_client: Any | None = None
        self._opensearch: Any | None = None
        self._embedding_model: Any | None = None
        self._embedding_deployment_name = ""
        self._embedding_cache: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._secret_cache: dict[str, dict[str, Any]] = {}

    def execute(self, tool_name: str, payload: dict[str, Any]) -> str:
        query = str(payload.get("query") or "")
        user_context = payload.get("user_context") if isinstance(payload.get("user_context"), dict) else {}
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        if tool_name in {"postgres_deterministic_lookup", "calendar_rota_lookup", "formulary_table_lookup", "table_lookup"}:
            return self.deterministic_lookup(query, user_context, tool_name=tool_name, extra=extra)
        if tool_name in {"document_search", "rag_search"}:
            return self.document_search(query, user_context)
        if tool_name == "policy_search":
            return self.policy_search(query, user_context)
        if tool_name in {"catalogue_search", "document_catalog"}:
            return self.catalogue_search(query, user_context)
        if tool_name == "safety_guard":
            return json.dumps(_safety_assessment(query), indent=2)
        return f"Tool {tool_name!r} is not registered for healthcare project."

    def _boto3_session(self):
        import boto3

        return boto3.Session(region_name=self.config.aws_region)

    def _s3(self):
        if self._s3_client is None:
            self._s3_client = self._boto3_session().client("s3", region_name=self.config.aws_region)
        return self._s3_client

    def _secret_json(self, secret_name: str) -> dict[str, Any]:
        if secret_name in self._secret_cache:
            return self._secret_cache[secret_name]
        client = self._boto3_session().client("secretsmanager", region_name=self.config.aws_region)
        response = client.get_secret_value(SecretId=secret_name)
        payload = json.loads((response.get("SecretString") or "{}").lstrip("\ufeffï»¿"))
        if not isinstance(payload, dict):
            payload = {}
        self._secret_cache[secret_name] = payload
        return payload

    def _azure_embedding_config(self) -> dict[str, str]:
        if self.config.use_local_resources():
            return {
                "endpoint": self.config.azure_openai_endpoint,
                "api_key": self.config.azure_openai_api_key,
                "api_version": self.config.azure_openai_api_version,
                "embedding_deployment": self.config.azure_openai_embedding_deployment,
            }
        secret = self._secret_json(self.config.azure_openai_secret_name)
        return {
            "endpoint": str(secret.get("endpoint") or self.config.azure_openai_endpoint),
            "api_key": str(secret.get("api_key") or self.config.azure_openai_api_key),
            "api_version": str(secret.get("api_version") or self.config.azure_openai_api_version),
            "embedding_deployment": str(
                secret.get("embedding_deployment") or self.config.azure_openai_embedding_deployment
            ),
        }

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            host=self.config.postgres_host,
            port=self.config.postgres_port,
            dbname=self.config.postgres_db,
            user=self.config.postgres_user,
            password=self.config.postgres_password,
            sslmode=self.config.postgres_sslmode,
            row_factory=dict_row,
            connect_timeout=3,
        )

    def deterministic_lookup(
        self,
        query: str,
        user_context: dict[str, Any],
        *,
        tool_name: str = "",
        extra: dict[str, Any] | None = None,
    ) -> str:
        extra = extra or {}
        user = user_context_from_payload(user_context)
        table_assets = extra.get("table_assets") if isinstance(extra.get("table_assets"), list) else None
        try:
            result = DeterministicLookupService(self.config).lookup(
                query,
                user,
                limit=50,
                table_assets=table_assets,
            )
            payload = json.loads(result.to_json())
            lookup_plan = payload.get("lookup_plan") if isinstance(payload.get("lookup_plan"), dict) else {}
            lookup_plan["source"] = "mcp_shared_core"
            lookup_plan["tool_name"] = tool_name
            payload["lookup_plan"] = lookup_plan
            return json.dumps(payload, indent=2, default=str)
        except Exception as exc:
            category = self._category_from_payload(query, tool_name, extra)
            scopes = _access_scopes(user_context)
            return json.dumps(
                {
                    "category": category,
                    "message": f"MCP shared deterministic lookup failed: {type(exc).__name__}: {exc}",
                    "access_scopes_applied": list(scopes),
                    "lookup_plan": {
                        "category": category,
                        "source": "mcp_shared_core",
                        "tool_name": tool_name,
                        "error": str(exc),
                    },
                    "rows": [],
                },
                indent=2,
            )

    def _category_from_payload(self, query: str, tool_name: str, extra: dict[str, Any]) -> str:
        category = _category(query, tool_name)
        table_assets = extra.get("table_assets") if isinstance(extra, dict) else None
        if not isinstance(table_assets, list):
            return category
        query_terms = set(_terms(query))
        best: tuple[int, str] = (0, category)
        table_to_category = {
            str(config["table"]).lower(): key
            for key, config in CRM_TABLES.items()
        }
        for asset in table_assets:
            if not isinstance(asset, dict):
                continue
            table_name = str(asset.get("table_name") or asset.get("source_table") or "").lower()
            candidate = table_to_category.get(table_name)
            if not candidate:
                continue
            haystack_terms = set(_terms(" ".join([
                table_name,
                str(asset.get("title") or ""),
                " ".join(str(column) for column in asset.get("columns") or []),
                " ".join(str(term) for term in asset.get("semantic_terms") or []),
                " ".join(str(value) for value in asset.get("sample_values") or []),
                json.dumps(asset.get("categorical_values") or {}),
            ])))
            score = len(query_terms & haystack_terms)
            if score > best[0]:
                best = (score, candidate)
        return best[1]

    def _access_sql(self) -> str:
        return "(lower(replace(COALESCE(access_level, 'all_staff'), ' ', '_')) = ANY(%s) OR access_level IS NULL)"

    def _query_table(self, category: str, query: str, scopes: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        config = CRM_TABLES[category]
        terms = _terms(query)
        q = query.lower()
        where_parts = [self._access_sql()]
        params: list[Any] = [list(scopes)]
        if category == "schedule":
            dates = _requested_dates(query)
            if dates:
                where_parts.append("shift_date::text = ANY(%s)")
                params.append(dates)
            if any(marker in q for marker in ["on call", "on-call", "oncall", "available"]):
                where_parts.append("on_call = true")
        useful_terms = [term for term in terms if term not in {"today", "tomorrow", "week", "next", "call", "oncall"}]
        if useful_terms and not ("list all" in q and category in {"departments", "equipment", "formulary"}):
            parts: list[str] = []
            for term in useful_terms[:8]:
                pattern = _like(term)
                term_parts = [f"lower(CAST({column} AS TEXT)) LIKE %s" for column in config["search"]]
                parts.append("(" + " OR ".join(term_parts) + ")")
                params.extend([pattern] * len(config["search"]))
            where_parts.append("(" + " OR ".join(parts) + ")")
        params.append(limit)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {", ".join(config["columns"])}
                    FROM {config["table"]}
                    WHERE {" AND ".join(where_parts)}
                    ORDER BY {config["pk"]}
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = []
                for result in cur.fetchall():
                    payload = dict(result)
                    rows.append(
                        {
                            "source_table": config["table"],
                            "source_filename": config["table"],
                            "row_number": payload.get(config["pk"]),
                            "row": payload,
                            "access_level": payload.get("access_level"),
                        }
                    )
                return rows

    def _manifest(self) -> list[dict[str, Any]]:
        ttl = max(0, self.config.document_manifest_cache_ttl_seconds)
        now = time.monotonic()
        if ttl and self._manifest_cache is not None and now < self._manifest_cache_expires_at:
            docs = self._manifest_cache.get("documents") if isinstance(self._manifest_cache, dict) else []
            return [doc for doc in docs if isinstance(doc, dict)]
        if not self.config.use_local_resources() and self.config.s3_bucket:
            try:
                response = self._s3().get_object(Bucket=self.config.s3_bucket, Key=self.config.manifest_key)
                data = json.loads(response["Body"].read().decode("utf-8"))
            except Exception:
                data = {"documents": []}
            if ttl:
                self._manifest_cache = data
                self._manifest_cache_expires_at = now + ttl
            docs = data.get("documents") if isinstance(data, dict) else []
            return [doc for doc in docs if isinstance(doc, dict)]

        path = Path(self.config.local_data_dir) / self.config.manifest_key
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"documents": []}
        if ttl:
            self._manifest_cache = data
            self._manifest_cache_expires_at = now + ttl
        docs = data.get("documents") if isinstance(data, dict) else []
        return [doc for doc in docs if isinstance(doc, dict)]

    def _raw_text(self, key: str) -> str:
        if not self.config.use_local_resources() and self.config.s3_bucket:
            try:
                response = self._s3().get_object(Bucket=self.config.s3_bucket, Key=key)
                return response["Body"].read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        path = (Path(self.config.local_data_dir) / key).resolve()
        root = Path(self.config.local_data_dir).resolve()
        if root not in path.parents and path != root:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def document_search(self, query: str, user_context: dict[str, Any]) -> str:
        if not self.config.use_local_resources() and self.config.opensearch_endpoint:
            hits = self._opensearch_search(query, user_context)
            if hits:
                return _format_retrieval_hits(hits)
        terms = _terms(query)
        hits: list[tuple[int, dict[str, Any], str]] = []
        for record in self._manifest():
            if int(record.get("chunk_count") or 0) == 0:
                continue
            key = str(record.get("key") or "")
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            if not _can_access_metadata(user_context, metadata):
                continue
            text = self._raw_text(key)
            haystack = " ".join([str(record.get("title") or ""), key, json.dumps(metadata), text]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                hits.append((score, record, text))
        hits.sort(key=lambda item: item[0], reverse=True)
        return _format_retrieval_hits(
            [
                {
                    "title": record.get("title") or record.get("key"),
                    "uri": record.get("uri"),
                    "score": score,
                    "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
                    "text": text,
                }
                for score, record, text in hits[: self.config.rag_top_k]
            ]
        )

    def _opensearch_client(self):
        if self._opensearch is not None:
            return self._opensearch
        from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

        credentials = self._boto3_session().get_credentials()
        auth = AWSV4SignerAuth(credentials, self.config.aws_region, "aoss")
        host = self.config.opensearch_endpoint.replace("https://", "").replace("http://", "")
        self._opensearch = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )
        return self._opensearch

    def _embed_query(self, query: str) -> list[float] | None:
        try:
            embedding_config = self._azure_embedding_config()
            deployment = embedding_config.get("embedding_deployment") or ""
            if not embedding_config.get("endpoint") or not embedding_config.get("api_key") or not deployment:
                return None
            if self._embedding_model is None:
                from langchain_openai import AzureOpenAIEmbeddings

                self._embedding_deployment_name = deployment
                self._embedding_model = AzureOpenAIEmbeddings(
                    azure_endpoint=embedding_config["endpoint"],
                    api_key=embedding_config["api_key"],
                    api_version=embedding_config["api_version"],
                    azure_deployment=deployment,
                )
            cache_key = (" ".join(query.lower().split()), self._embedding_deployment_name)
            if self.config.rag_embedding_cache_size > 0 and cache_key in self._embedding_cache:
                vector = self._embedding_cache.pop(cache_key)
                self._embedding_cache[cache_key] = vector
                return list(vector)
            vector = list(self._embedding_model.embed_query(query))
            if self.config.rag_embedding_cache_size > 0:
                self._embedding_cache[cache_key] = vector
                while len(self._embedding_cache) > self.config.rag_embedding_cache_size:
                    self._embedding_cache.popitem(last=False)
            return vector
        except Exception:
            return None

    def _opensearch_search(self, query: str, user_context: dict[str, Any]) -> list[dict[str, Any]]:
        client = self._opensearch_client()
        result_limit = max(1, self.config.rag_top_k)
        bodies: list[dict[str, Any]] = []
        vector = self._embed_query(query)
        if vector:
            bodies.append(
                {
                    "size": result_limit,
                    "query": {
                        "knn": {
                            "embedding": {
                                "vector": vector,
                                "k": result_limit,
                            }
                        }
                    },
                }
            )
        bodies.append(
            {
                "size": result_limit,
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["text^2", "title^3", "key^3", "metadata.*"],
                    }
                },
            }
        )

        raw_hits: list[dict[str, Any]] = []
        for body in bodies:
            try:
                response = client.search(index=self.config.opensearch_index, body=body)
            except Exception:
                continue
            raw_hits.extend(self._hits_from_opensearch_response(response, user_context))
        return self._merge_hits(raw_hits)[:result_limit]

    def _hits_from_opensearch_response(
        self,
        response: dict[str, Any],
        user_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            metadata = dict(source.get("metadata", {}))
            if not _can_access_metadata(user_context, metadata):
                continue
            metadata.setdefault("_key", source.get("key"))
            metadata.setdefault("_chunk_index", source.get("chunk_index"))
            metadata.setdefault("_content_type", source.get("content_type"))
            metadata.setdefault("_checksum", source.get("checksum"))
            hits.append(
                {
                    "title": str(source.get("title") or source.get("key") or "Untitled"),
                    "uri": str(source.get("uri") or source.get("source") or ""),
                    "key": str(source.get("key") or ""),
                    "chunk_index": source.get("chunk_index"),
                    "text": str(source.get("text") or ""),
                    "score": float(hit.get("_score")) if hit.get("_score") is not None else None,
                    "metadata": metadata,
                }
            )
        return hits

    def _merge_hits(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        merged: list[dict[str, Any]] = []
        for hit in hits:
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            key = str(metadata.get("_key") or hit.get("key") or hit.get("uri") or "")
            raw_chunk_index = metadata.get("_chunk_index") or hit.get("chunk_index")
            chunk_index = "" if raw_chunk_index is None else str(raw_chunk_index)
            identity = (key, chunk_index, str(hit.get("text") or "")[:80])
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(hit)
        return merged

    def policy_search(self, query: str, user_context: dict[str, Any]) -> str:
        if not self.config.use_local_resources() and self.config.opensearch_endpoint:
            hits = [
                hit
                for hit in self._opensearch_search(query, user_context)
                if _metadata_is_policy(
                    hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {},
                    str(hit.get("title") or ""),
                )
            ]
            if hits:
                return _format_retrieval_hits(hits)
        policy_records = []
        for record in self._manifest():
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            title = str(record.get("title") or record.get("key") or "").lower()
            if _can_access_metadata(user_context, metadata) and _metadata_is_policy(metadata, title):
                policy_records.append(record)
        if not policy_records:
            return self.document_search(query, user_context)
        original_manifest = self._manifest
        try:
            self._manifest = lambda: policy_records  # type: ignore[method-assign]
            return self.document_search(query, user_context)
        finally:
            self._manifest = original_manifest  # type: ignore[method-assign]

    def catalogue_search(self, query: str, user_context: dict[str, Any]) -> str:
        terms = _terms(query)
        matches = []
        for record in self._manifest():
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            if not _can_access_metadata(user_context, metadata):
                continue
            haystack = " ".join([str(record.get("title") or ""), str(record.get("key") or ""), json.dumps(metadata)]).lower()
            if not terms or any(term in haystack for term in terms):
                matches.append(
                    {
                        "title": record.get("title"),
                        "uri": record.get("uri"),
                        "content_type": record.get("content_type"),
                        "metadata": metadata,
                    }
                )
        return json.dumps(matches[:20], indent=2, default=str)


HEALTHCARE_PROJECT_ID = "dstrmaysam-healthcare-knowledge-multi-agent"


PROJECT_ALIASES = {
    "dstrmaysam-healthcare-knowledge-multi-agent",
    "dstrmaysam_healthcare_knowledge_multi_agent",
    "healthcare_knowledge_multi_agent",
    os.getenv("MCP_DEFAULT_PROJECT_ID", "dstrmaysam-healthcare-knowledge-multi-agent"),
}
