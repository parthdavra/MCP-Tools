from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _project_backend_path() -> Path:
    configured = os.getenv("ZED_HEALTH_BACKEND_PATH", "").strip()
    if configured:
        return Path(configured)
    resolved = Path(__file__).resolve()
    for parent in resolved.parents:
        candidate = parent / "Project Healthcare" / "backend"
        if candidate.exists():
            return candidate
    return Path("C:/Users/fakha/itc/Project Healthcare/backend")


backend_path = _project_backend_path()
if not backend_path.exists():
    raise RuntimeError(
        "ZED Healthcare backend path was not found. Set ZED_HEALTH_BACKEND_PATH "
        "to the Project Healthcare backend directory."
    )

import sys

backend_path_text = str(backend_path)
if backend_path_text not in sys.path:
    sys.path.insert(0, backend_path_text)

from app.mcp.healthcare_tools import HealthcareTools  # noqa: E402


def _data_dir() -> Path:
    return Path(os.getenv("ZED_HEALTH_DATA_DIR") or os.getenv("DATA_DIR") or backend_path.parent / "data")


def _roles(payload: dict[str, Any]) -> list[str]:
    roles = payload.get("roles")
    if isinstance(roles, list):
        return [str(role) for role in roles if str(role).strip()]
    user_context = payload.get("user_context")
    if isinstance(user_context, dict) and isinstance(user_context.get("roles"), list):
        return [str(role) for role in user_context["roles"] if str(role).strip()]
    return []


class ZedHealthcareTools:
    def __init__(self, tools: HealthcareTools):
        self.tools = tools

    @classmethod
    def from_env(cls) -> "ZedHealthcareTools":
        return cls(HealthcareTools.from_data_dir(_data_dir()))

    def search_policy_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.search_policy_documents(
            query=str(payload.get("query") or ""),
            top_k=int(payload.get("top_k") or 5),
            roles=_roles(payload),
        )

    def search_all_lookup_tables(self, payload: dict[str, Any]) -> dict[str, Any]:
        excluded_tables = payload.get("excluded_tables")
        if isinstance(excluded_tables, list):
            excluded = {str(table) for table in excluded_tables}
        else:
            excluded = set()
        return self.tools.search_all_lookup_tables(
            query=str(payload.get("query") or ""),
            max_rows_per_table=int(payload.get("max_rows_per_table") or 10),
            excluded_tables=excluded,
            patient_id=payload.get("patient_id"),
            include_patient_labs=bool(payload.get("include_patient_labs", False)),
            roles=_roles(payload),
        )

    def lookup_doctor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.lookup_doctor(str(payload.get("query") or ""))

    def lookup_availability(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.lookup_availability(str(payload.get("query") or ""))

    def lookup_nurse_in_charge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.lookup_nurse_in_charge(str(payload.get("department") or "ICU"))

    def get_patient_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_patient_profile(str(payload.get("patient_id") or ""))

    def get_assigned_doctor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_assigned_doctor(str(payload.get("patient_id") or ""))

    def get_patient_appointments(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_patient_appointments(str(payload.get("patient_id") or ""))

    def get_patient_lab_reports(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_patient_lab_reports(str(payload.get("patient_id") or ""))

    def get_patient_lab_report_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_patient_lab_report_details(
            str(payload.get("patient_id") or ""),
            str(payload.get("report_id") or ""),
        )

    def summarise_lab_reports(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.summarise_lab_reports(
            str(payload.get("patient_id") or ""),
            max_reports=int(payload.get("max_reports") or 3),
        )

    def book_patient_appointment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.book_patient_appointment(
            authenticated_patient_id=str(payload.get("patient_id") or ""),
            doctor_id=str(payload.get("doctor_id") or ""),
            appointment_date=str(payload.get("appointment_date") or ""),
            appointment_time=str(payload.get("appointment_time") or ""),
            reason=str(payload.get("reason") or "Patient requested appointment"),
        )

    def get_guardian_nhs_news(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.get_guardian_nhs_news(limit=int(payload.get("limit") or 10))

    def list_policy_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.list_policy_documents()

    def list_lookup_csv_documents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.list_lookup_csv_documents()

    def store_chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.tools.store_chat_message(
            username=str(payload.get("username") or ""),
            role=str(payload.get("role") or ""),
            content=str(payload.get("content") or ""),
            route=str(payload.get("route") or ""),
        )
        return {"stored": True}

    def list_chat_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.list_chat_history(
            username=str(payload.get("username") or ""),
            limit=int(payload.get("limit") or 50),
        )
