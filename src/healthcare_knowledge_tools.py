from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
    local_data_dir: str
    manifest_key: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_sslmode: str

    @classmethod
    def from_env(cls) -> "HealthcareMcpConfig":
        return cls(
            local_data_dir=os.getenv("HEALTHCARE_LOCAL_DATA_DIR", "/app/data"),
            manifest_key=os.getenv("HEALTHCARE_MANIFEST_KEY", "manifests/documents.json"),
            postgres_host=os.getenv("POSTGRES_HOST", "host.docker.internal"),
            postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
            postgres_db=os.getenv("POSTGRES_DB", "healthcare_agent"),
            postgres_user=os.getenv("POSTGRES_USER", "healthcare_agent"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", "healthcare_agent_dev"),
            postgres_sslmode=os.getenv("POSTGRES_SSLMODE", "disable"),
        )


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

    def execute(self, tool_name: str, payload: dict[str, Any]) -> str:
        query = str(payload.get("query") or "")
        user_context = payload.get("user_context") if isinstance(payload.get("user_context"), dict) else {}
        if tool_name in {"postgres_deterministic_lookup", "calendar_rota_lookup", "formulary_table_lookup", "table_lookup"}:
            return self.deterministic_lookup(query, user_context, tool_name=tool_name)
        if tool_name in {"document_search", "rag_search"}:
            return self.document_search(query, user_context)
        if tool_name == "policy_search":
            return self.policy_search(query, user_context)
        if tool_name in {"catalogue_search", "document_catalog"}:
            return self.catalogue_search(query, user_context)
        if tool_name == "safety_guard":
            return json.dumps({"risk_level": "unknown", "mcp_assessed": True, "query": query}, indent=2)
        return f"Tool {tool_name!r} is not registered for healthcare project."

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

    def deterministic_lookup(self, query: str, user_context: dict[str, Any], *, tool_name: str = "") -> str:
        category = _category(query, tool_name)
        scopes = _access_scopes(user_context)
        limit = 50
        try:
            rows = self._query_table(category, query, scopes, limit)
            aggregate_result = None
            if "how many" in query.lower() or "count" in query.lower() or "total" in query.lower():
                aggregate_result = {
                    "type": "count",
                    "matching_rows": len(rows),
                    "counts_by_source": {CRM_TABLES[category]["table"]: len(rows)},
                    "source_tables": [CRM_TABLES[category]["table"]],
                }
            message = "No matching rows found." if not rows else f"Found {len(rows)} matching row(s)."
            return json.dumps(
                {
                    "category": category,
                    "message": message,
                    "access_scopes_applied": list(scopes),
                    "lookup_plan": {
                        "category": category,
                        "aggregate_intent": "count" if aggregate_result else "",
                        "aggregate_result": aggregate_result,
                        "matched_table_sources": [CRM_TABLES[category]["table"]] if rows else [],
                        "resolved_today": date.today().isoformat(),
                        "requested_rota_dates": _requested_dates(query),
                        "source": "mcp_postgres",
                    },
                    "rows": rows,
                },
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "category": category,
                    "message": f"MCP Postgres deterministic lookup failed: {type(exc).__name__}: {exc}",
                    "access_scopes_applied": list(scopes),
                    "lookup_plan": {"category": category, "source": "mcp_postgres", "error": str(exc)},
                    "rows": [],
                },
                indent=2,
            )

    def _query_table(self, category: str, query: str, scopes: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        config = CRM_TABLES[category]
        terms = _terms(query)
        q = query.lower()
        where_parts = ["(access_level = ANY(%s) OR access_level IS NULL)"]
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
        path = Path(self.config.local_data_dir) / self.config.manifest_key
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            docs = data.get("documents") if isinstance(data, dict) else []
            return [doc for doc in docs if isinstance(doc, dict)]
        except Exception:
            return []

    def _raw_text(self, key: str) -> str:
        path = (Path(self.config.local_data_dir) / key).resolve()
        root = Path(self.config.local_data_dir).resolve()
        if root not in path.parents and path != root:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def document_search(self, query: str, user_context: dict[str, Any]) -> str:
        terms = _terms(query)
        hits: list[tuple[int, dict[str, Any], str]] = []
        for record in self._manifest():
            if int(record.get("chunk_count") or 0) == 0:
                continue
            key = str(record.get("key") or "")
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            text = self._raw_text(key)
            haystack = " ".join([str(record.get("title") or ""), key, json.dumps(metadata), text]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                hits.append((score, record, text))
        hits.sort(key=lambda item: item[0], reverse=True)
        if not hits:
            return "No relevant document chunks found."
        lines = []
        for index, (score, record, text) in enumerate(hits[:10], start=1):
            lines.append(
                f"[{index}] {record.get('title') or record.get('key')} ({record.get('uri')}, score={score})\n{text[:1200]}"
            )
        return "\n\n".join(lines)

    def policy_search(self, query: str, user_context: dict[str, Any]) -> str:
        policy_records = []
        for record in self._manifest():
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            domain = str(metadata.get("domain") or "").lower()
            document_type = str(metadata.get("document_type") or "").lower()
            title = str(record.get("title") or record.get("key") or "").lower()
            if domain in {"clinical_policy", "admin_policy", "compliance"} or document_type in {"policy", "sop", "pathway", "guideline"} or "policy" in title:
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
