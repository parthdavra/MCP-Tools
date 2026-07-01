from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _csv_text_to_rows(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _rows_to_csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return handle.getvalue()


def _split_roles(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,|]", value or "") if item.strip()]


def _join_roles(roles: list[str]) -> str:
    return ",".join(sorted({role.strip() for role in roles if role.strip()}))


STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "for",
    "from",
    "have",
    "is",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "show",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
}


def _terms(query: str) -> list[str]:
    typo_normalisations = {
        "servere": "severe",
        "incharge": "charge",
    }
    terms = []
    for term in re.findall(r"[a-z0-9]+", query.lower()):
        if term in STOPWORDS or len(term) <= 1:
            continue
        term = typo_normalisations.get(term, term)
        if len(term) > 4 and term.endswith("ies"):
            term = term[:-3] + "y"
        elif len(term) > 4 and term.endswith("ses"):
            term = term[:-1]
        elif len(term) > 3 and term.endswith("es"):
            term = term[:-2]
        elif len(term) > 3 and term.endswith("s"):
            term = term[:-1]
        terms.append(term)
    return terms


def _row_text(row: dict[str, str]) -> str:
    values = list(row.keys()) + [str(value) for value in row.values()]
    return " ".join(values).lower()


def _row_score(row: dict[str, str], query_terms: list[str]) -> int:
    text = _row_text(row)
    return sum(1 for term in query_terms if term in text)


def _contains(row: dict[str, str], query: str) -> bool:
    terms = _terms(query)
    if not terms:
        return False
    matches = _row_score(row, terms)
    return matches >= min(2, len(terms))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_pages(path: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []

    try:
        reader = PdfReader(str(path))
    except Exception:
        return []

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = _clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if text:
            pages.append({"page": index, "text": text})
    return pages


def _extract_text_pages(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_pages(path)
    try:
        text = _clean_text(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        text = ""
    return [{"page": None, "text": text}] if text else []


def _best_passage(text: str, query_terms: list[str], window_chars: int = 1200) -> tuple[int, str]:
    lowered = text.lower()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
    if positions:
        center = min(positions)
        score = sum(1 for term in query_terms if term in lowered)
    else:
        center = 0
        score = 0
    start = max(0, center - window_chars // 3)
    end = min(len(text), start + window_chars)
    return score, text[start:end].strip()


def _chunks(text: str, chunk_chars: int = 700, overlap: int = 140) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _term_vector(text: str) -> dict[str, int]:
    vector: dict[str, int] = {}
    for term in _terms(text):
        vector[term] = vector.get(term, 0) + 1
    return vector


def _cosine_similarity(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(left[key] * right[key] for key in shared)
    left_norm = sum(value * value for value in left.values()) ** 0.5
    right_norm = sum(value * value for value in right.values()) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


@dataclass
class HealthcareTools:
    data_dir: Path
    STRUCTURED_TABLES = {
        "patients.csv": "patients",
        "doctors.csv": "doctors",
        "appointments.csv": "appointments",
        "lab_reports.csv": "lab_reports",
        "lab_results.csv": "lab_results",
        "patient_users.csv": "patient_users",
        "nhs_guardian_news.csv": "nhs_guardian_news",
    }

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> "HealthcareTools":
        return cls(Path(data_dir))

    def _database_url(self) -> str:
        explicit = (
            os.getenv("DATABASE_URL")
            or os.getenv("POSTGRES_DSN")
            or os.getenv("RDS_DATABASE_URL")
            or os.getenv("RDS_POSTGRES_DSN")
            or ""
        )
        if explicit:
            return explicit
        host = os.getenv("RDS_POSTGRES_HOST") or ""
        if host:
            secret = self._aws_secret()
            user = os.getenv("RDS_POSTGRES_USER") or secret.get("username") or secret.get("user") or ""
            password = os.getenv("RDS_POSTGRES_PASSWORD") or secret.get("password") or ""
            db_name = os.getenv("RDS_POSTGRES_DB") or secret.get("dbname") or secret.get("database") or "postgres"
            port = os.getenv("RDS_POSTGRES_PORT") or str(secret.get("port") or "5432")
            if user and password:
                sslmode = os.getenv("RDS_POSTGRES_SSLMODE", "require")
                return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db_name}?sslmode={sslmode}"
        host = os.getenv("POSTGRES_HOST") or ""
        if host:
            user = os.getenv("POSTGRES_USER", "")
            password = os.getenv("POSTGRES_PASSWORD", "")
            db_name = os.getenv("POSTGRES_DB", "postgres")
            port = os.getenv("POSTGRES_PORT", "5432")
            sslmode = os.getenv("POSTGRES_SSLMODE", "disable")
            if user and password:
                return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db_name}?sslmode={sslmode}"
        return ""

    def _aws_secret(self) -> dict[str, Any]:
        secret_id = os.getenv("RDS_MASTER_SECRET_ARN") or os.getenv("APP_SECRET_NAME") or ""
        if not secret_id:
            return {}
        try:
            import boto3

            response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
            raw_secret = response.get("SecretString") or "{}"
            value = json.loads(raw_secret)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _db_available(self) -> bool:
        return bool(self._database_url())

    def _db_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._database_url(), row_factory=dict_row)

    def _fieldnames_for(self, csv_name: str) -> list[str]:
        rows = _read_csv(self.data_dir / csv_name)
        if rows:
            return list(rows[0].keys())
        defaults = {
            "patient_users.csv": ["username", "patient_id", "demo_password", "roles", "status"],
            "appointments.csv": [
                "appointment_id",
                "patient_id",
                "doctor_id",
                "appointment_date",
                "appointment_time",
                "appointment_type",
                "status",
                "location",
                "reason",
            ],
        }
        return defaults.get(csv_name, [])

    def _ensure_db_table(self, csv_name: str) -> None:
        table = self.STRUCTURED_TABLES.get(csv_name)
        fieldnames = self._fieldnames_for(csv_name)
        if not table or not fieldnames:
            return
        with self._db_connect() as conn:
            with conn.cursor() as cur:
                columns = ", ".join(f'"{name}" text' for name in fieldnames)
                cur.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({columns})')
                cur.execute(f'SELECT COUNT(*) AS count FROM "{table}"')
                count = int(cur.fetchone()["count"])
                seed_rows = _read_csv(self.data_dir / csv_name)
                if count == 0 and seed_rows:
                    placeholders = ", ".join(["%s"] * len(fieldnames))
                    column_names = ", ".join(f'"{name}"' for name in fieldnames)
                    values = [[row.get(name, "") for name in fieldnames] for row in seed_rows]
                    cur.executemany(f'INSERT INTO "{table}" ({column_names}) VALUES ({placeholders})', values)

    def _db_rows(self, csv_name: str) -> list[dict[str, str]]:
        table = self.STRUCTURED_TABLES.get(csv_name)
        if not table or not self._db_available():
            return _read_csv(self.data_dir / csv_name)
        self._ensure_db_table(csv_name)
        with self._db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM "{table}"')
                return [{key: "" if value is None else str(value) for key, value in row.items()} for row in cur.fetchall()]

    def _replace_db_rows(self, csv_name: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
        table = self.STRUCTURED_TABLES.get(csv_name)
        if not table or not self._db_available():
            _write_csv(self.data_dir / csv_name, rows, fieldnames)
            return
        self._ensure_db_table(csv_name)
        with self._db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM "{table}"')
                if rows:
                    placeholders = ", ".join(["%s"] * len(fieldnames))
                    column_names = ", ".join(f'"{name}"' for name in fieldnames)
                    values = [[row.get(name, "") for name in fieldnames] for row in rows]
                    cur.executemany(f'INSERT INTO "{table}" ({column_names}) VALUES ({placeholders})', values)

    def _ensure_chat_history_table(self) -> None:
        if not self._db_available():
            return
        with self._db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id text PRIMARY KEY,
                        username text NOT NULL,
                        role text NOT NULL,
                        content text NOT NULL,
                        route text,
                        created_at text NOT NULL
                    )
                    """
                )

    def store_chat_message(self, username: str, role: str, content: str, route: str = "") -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        record = {
            "id": uuid4().hex,
            "username": username,
            "role": role,
            "content": content,
            "route": route,
            "created_at": created_at,
        }
        if self._db_available():
            self._ensure_chat_history_table()
            with self._db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO chat_history (id, username, role, content, route, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (record["id"], username, role, content, route, created_at),
                    )
            return
        bucket = self._document_bucket()
        if bucket:
            safe_username = re.sub(r"[^A-Za-z0-9._-]+", "_", username)
            self._s3_client().put_object(
                Bucket=bucket,
                Key=f"chat_history/{safe_username}/{created_at}_{record['id']}.json",
                Body=json.dumps(record).encode("utf-8"),
            )

    def list_chat_history(self, username: str, limit: int = 50) -> dict[str, Any]:
        if self._db_available():
            self._ensure_chat_history_table()
            with self._db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT role, content, route, created_at
                        FROM chat_history
                        WHERE username = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (username, limit),
                    )
                    rows = list(reversed(cur.fetchall()))
                    return {"messages": rows}
        bucket = self._document_bucket()
        if bucket:
            safe_username = re.sub(r"[^A-Za-z0-9._-]+", "_", username)
            prefix = f"chat_history/{safe_username}/"
            objects = self._s3_client().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
            messages = []
            for item in sorted(objects, key=lambda row: row.get("Key", ""))[-limit:]:
                try:
                    body = self._s3_client().get_object(Bucket=bucket, Key=item["Key"])["Body"].read()
                    messages.append(json.loads(body.decode("utf-8")))
                except Exception:
                    continue
            return {"messages": messages}
        return {"messages": []}

    def _rows(self, name: str) -> list[dict[str, str]]:
        return self._db_rows(name)

    def find_patient_user(self, username: str) -> dict[str, str] | None:
        for row in self._rows("patient_users.csv"):
            if row.get("username") == username and row.get("status", "active") == "active":
                return row
        return None

    def find_any_patient_user(self, username: str) -> dict[str, str] | None:
        for row in self._rows("patient_users.csv"):
            if row.get("username") == username:
                return row
        return None

    def list_patient_users(self) -> dict[str, Any]:
        rows = []
        for row in self._rows("patient_users.csv"):
            safe_row = dict(row)
            safe_row.pop("demo_password", None)
            safe_row["roles"] = _split_roles(safe_row.get("roles", "patient"))
            safe_row["editable"] = True
            rows.append(safe_row)
        return {"users": rows}

    def create_patient_user(
        self,
        username: str,
        patient_id: str,
        temporary_password: str,
        roles: list[str],
        status: str = "active",
    ) -> dict[str, Any]:
        if self.find_any_patient_user(username):
            raise ValueError("Patient user already exists")
        if not any(row.get("patient_id") == patient_id for row in self._rows("patients.csv")):
            raise ValueError("Patient ID does not exist")
        rows = self._rows("patient_users.csv")
        row = {
            "username": username,
            "patient_id": patient_id,
            "demo_password": temporary_password,
            "roles": _join_roles(roles or ["patient"]),
            "status": status or "active",
        }
        rows.append(row)
        self._replace_db_rows("patient_users.csv", rows, ["username", "patient_id", "demo_password", "roles", "status"])
        return {**row, "roles": _split_roles(row["roles"]), "type": "patient", "editable": True}

    def update_patient_user(self, username: str, roles: list[str], status: str = "active") -> dict[str, Any]:
        rows = self._rows("patient_users.csv")
        for row in rows:
            if row.get("username") == username:
                row["roles"] = _join_roles(roles or ["patient"])
                row["status"] = status or "active"
                self._replace_db_rows("patient_users.csv", rows, ["username", "patient_id", "demo_password", "roles", "status"])
                safe_row = dict(row)
                safe_row.pop("demo_password", None)
                return {**safe_row, "roles": _split_roles(row["roles"]), "type": "patient", "editable": True}
        raise ValueError("Patient user not found")

    def reset_patient_user_password(self, username: str, temporary_password: str) -> dict[str, Any]:
        rows = self._rows("patient_users.csv")
        for row in rows:
            if row.get("username") == username:
                row["demo_password"] = temporary_password
                self._replace_db_rows("patient_users.csv", rows, ["username", "patient_id", "demo_password", "roles", "status"])
                return {"username": username, "status": "password_reset"}
        raise ValueError("Patient user not found")

    def delete_patient_user(self, username: str) -> dict[str, Any]:
        rows = self._rows("patient_users.csv")
        kept_rows = [row for row in rows if row.get("username") != username]
        if len(kept_rows) == len(rows):
            raise ValueError("Patient user not found")
        self._replace_db_rows("patient_users.csv", kept_rows, ["username", "patient_id", "demo_password", "roles", "status"])
        return {"username": username, "status": "deleted"}

    def list_patients(self) -> dict[str, Any]:
        return {"patients": self._rows("patients.csv")}

    def _document_access_path(self) -> Path:
        return self.data_dir / "document_access.csv"

    def _document_access_rows(self) -> list[dict[str, str]]:
        bucket = self._document_bucket()
        if bucket:
            try:
                body = self._s3_client().get_object(Bucket=bucket, Key="metadata/document_access.csv")["Body"].read()
                return _csv_text_to_rows(body.decode("utf-8-sig"))
            except Exception:
                return []
        return _read_csv(self._document_access_path())

    def _write_document_access_rows(self, rows: list[dict[str, Any]]) -> None:
        fieldnames = ["title", "doc_type", "allowed_roles", "s3_bucket", "s3_key", "uploaded_at"]
        bucket = self._document_bucket()
        if bucket:
            self._s3_client().put_object(
                Bucket=bucket,
                Key="metadata/document_access.csv",
                Body=_rows_to_csv_text(rows, fieldnames).encode("utf-8"),
            )
            return
        _write_csv(self._document_access_path(), rows, fieldnames)

    def _document_bucket(self) -> str:
        return os.getenv("POLICY_S3_BUCKET") or os.getenv("S3_BUCKET") or ""

    def _s3_client(self):
        import boto3

        return boto3.client("s3")

    def _bootstrap_s3_from_local(self, prefix: str, local_dir: Path, suffixes: tuple[str, ...]) -> None:
        bucket = self._document_bucket()
        if not bucket or os.getenv("BOOTSTRAP_LOCAL_DATA_TO_AWS", "true").lower() not in {"1", "true", "yes"}:
            return
        try:
            client = self._s3_client()
            existing = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0)
            if existing or not local_dir.exists():
                return
            for path in sorted(local_dir.glob("*")):
                if path.is_file() and path.suffix.lower() in suffixes:
                    client.put_object(Bucket=bucket, Key=f"{prefix}{path.name}", Body=path.read_bytes())
        except Exception:
            return

    def _s3_csv_objects(self) -> list[dict[str, str]]:
        bucket = self._document_bucket()
        if not bucket:
            return []
        try:
            self._bootstrap_s3_from_local("lookups/", self.data_dir / "lookups" / "phase1", (".csv",))
            client = self._s3_client()
            token = None
            objects: list[dict[str, str]] = []
            while True:
                kwargs: dict[str, str] = {"Bucket": bucket}
                if token:
                    kwargs["ContinuationToken"] = token
                response = client.list_objects_v2(**kwargs)
                for item in response.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if key.lower().endswith(".csv"):
                        objects.append({"bucket": bucket, "key": key, "title": Path(key).name})
                if not response.get("IsTruncated"):
                    return objects
                token = response.get("NextContinuationToken")
        except Exception:
            return []

    def _sync_lookup_csvs_from_s3(self) -> None:
        lookup_dir = self.data_dir / "lookups" / "phase1"
        lookup_dir.mkdir(parents=True, exist_ok=True)
        objects = self._s3_csv_objects()
        if not objects:
            return
        try:
            client = self._s3_client()
            for item in objects:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", item["title"])
                if safe_name and not (lookup_dir / safe_name).exists():
                    client.download_file(item["bucket"], item["key"], str(lookup_dir / safe_name))
        except Exception:
            return

    def _s3_policy_objects(self) -> list[dict[str, str]]:
        bucket = self._document_bucket()
        if not bucket:
            return []
        try:
            self._bootstrap_s3_from_local("policies/", self.data_dir / "policies", (".pdf", ".txt", ".md"))
            client = self._s3_client()
            objects: list[dict[str, str]] = []
            token = None
            while True:
                kwargs: dict[str, str] = {"Bucket": bucket, "Prefix": "policies/"}
                if token:
                    kwargs["ContinuationToken"] = token
                response = client.list_objects_v2(**kwargs)
                for item in response.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if key.lower().endswith((".pdf", ".txt", ".md")):
                        objects.append({"bucket": bucket, "key": key, "title": Path(key).name})
                if not response.get("IsTruncated"):
                    return objects
                token = response.get("NextContinuationToken")
        except Exception:
            return []

    def _s3_text_object(self, bucket: str, key: str) -> str:
        body = self._s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        if key.lower().endswith(".pdf"):
            tmp_path = self.data_dir / ".aws_cache" / Path(key).name
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(body)
            pages = _extract_text_pages(tmp_path)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return "\n\n".join(str(page["text"]) for page in pages)
        return body.decode("utf-8-sig", errors="ignore")

    def _lookup_csv_tables(self) -> list[tuple[str, list[dict[str, str]]]]:
        lookup_dir = self.data_dir / "lookups" / "phase1"
        local_tables = {
            path.name: _read_csv(path)
            for path in sorted(lookup_dir.glob("*.csv"))
        } if lookup_dir.exists() else {}
        bucket = self._document_bucket()
        if bucket:
            tables_by_title: dict[str, list[dict[str, str]]] = {}
            for item in self._s3_csv_objects():
                key = item["key"]
                if not key.lower().endswith(".csv") or key.startswith("metadata/"):
                    continue
                try:
                    body = self._s3_client().get_object(Bucket=item["bucket"], Key=key)["Body"].read()
                    tables_by_title[item["title"]] = _csv_text_to_rows(body.decode("utf-8-sig", errors="ignore"))
                except Exception:
                    continue
            for title, rows in local_tables.items():
                tables_by_title.setdefault(title, rows)
            return list(tables_by_title.items())
        return list(local_tables.items())

    def _opensearch_endpoint(self) -> str:
        return (
            os.getenv("OPENSEARCH_ENDPOINT")
            or os.getenv("OPENSEARCH_COLLECTION_ENDPOINT")
            or os.getenv("AOSS_COLLECTION_ENDPOINT")
            or ""
        ).replace("https://", "").rstrip("/")

    def _opensearch_index(self) -> str:
        return os.getenv("OPENSEARCH_POLICY_INDEX", "zed-healthcare-policies")

    def _opensearch_client(self):
        endpoint = self._opensearch_endpoint()
        if not endpoint:
            return None
        try:
            import boto3
            from opensearchpy import OpenSearch, RequestsHttpConnection
            from opensearchpy.helpers.signer import AWSV4SignerAuth

            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-west-2"
            auth = AWSV4SignerAuth(boto3.Session().get_credentials(), region, "aoss")
            return OpenSearch(
                hosts=[{"host": endpoint, "port": 443}],
                http_auth=auth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=30,
            )
        except Exception:
            return None

    def _ensure_policy_index(self) -> Any | None:
        client = self._opensearch_client()
        if not client:
            return None
        index = self._opensearch_index()
        try:
            if not client.indices.exists(index=index):
                client.indices.create(
                    index=index,
                    body={
                        "settings": {"index": {"knn": False}},
                        "mappings": {
                            "properties": {
                                "title": {"type": "keyword"},
                                "s3_key": {"type": "keyword"},
                                "chunk": {"type": "integer"},
                                "text": {"type": "text"},
                                "allowed_roles": {"type": "keyword"},
                            }
                        },
                    },
                )
            return client
        except Exception:
            return None

    def _index_policy_document(self, title: str, s3_key: str, allowed_roles: list[str], content: bytes | None = None) -> None:
        client = self._ensure_policy_index()
        bucket = self._document_bucket()
        if not client or not bucket or not s3_key:
            return
        try:
            if content is not None and not title.lower().endswith(".pdf"):
                text = content.decode("utf-8-sig", errors="ignore")
            else:
                text = self._s3_text_object(bucket, s3_key)
            for chunk_index, chunk in enumerate(_chunks(text), start=1):
                client.index(
                    index=self._opensearch_index(),
                    id=f"{s3_key}:{chunk_index}",
                    body={
                        "title": title,
                        "s3_key": s3_key,
                        "chunk": chunk_index,
                        "text": chunk,
                        "allowed_roles": allowed_roles or ["all_staff"],
                    },
                    refresh=False,
                )
        except Exception:
            return

    def _search_policy_opensearch(self, query: str, top_k: int, roles: list[str] | None) -> list[dict[str, Any]]:
        client = self._ensure_policy_index()
        if not client:
            return []
        role_terms = roles or []
        role_terms = [*role_terms, "all_staff"] if "patient" not in role_terms else role_terms
        try:
            response = client.search(
                index=self._opensearch_index(),
                body={
                    "size": top_k,
                    "query": {
                        "bool": {
                            "must": [{"match": {"text": query}}],
                            "filter": [{"terms": {"allowed_roles": role_terms}}],
                        }
                    },
                },
            )
            hits = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                hits.append(
                    {
                        "title": source.get("title", ""),
                        "path": source.get("s3_key", ""),
                        "score": hit.get("_score", 0),
                        "page": None,
                        "chunk": source.get("chunk"),
                        "snippet": source.get("text", ""),
                        "text_extracted": True,
                        "retrieval_mode": "opensearch",
                    }
                )
            return hits
        except Exception:
            return []

    def _document_allowed_for_roles(self, title: str, roles: list[str] | None) -> bool:
        rows = self._document_access_rows()
        if not rows:
            return True
        matching = [row for row in rows if row.get("title") == title]
        if not matching:
            return True
        role_set = set(roles or [])
        allowed_roles = set(_split_roles(matching[0].get("allowed_roles", "")))
        if not allowed_roles:
            return False
        return bool(role_set & allowed_roles or "all_staff" in allowed_roles and "patient" not in role_set)

    def _upsert_document_access(
        self,
        *,
        title: str,
        allowed_roles: list[str],
        doc_type: str,
        s3_bucket: str = "",
        s3_key: str = "",
        uploaded_at: str = "",
    ) -> None:
        rows = [row for row in self._document_access_rows() if row.get("title") != title]
        rows.append(
            {
                "title": title,
                "doc_type": doc_type,
                "allowed_roles": _join_roles(allowed_roles),
                "s3_bucket": s3_bucket,
                "s3_key": s3_key,
                "uploaded_at": uploaded_at,
            }
        )
        self._write_document_access_rows(rows)

    # Policy RAG tools
    def search_policy_documents(self, query: str, top_k: int = 5, roles: list[str] | None = None) -> dict[str, Any]:
        opensearch_hits = self._search_policy_opensearch(query, top_k, roles)
        if opensearch_hits:
            return {"query": query, "hits": opensearch_hits}
        if self._opensearch_endpoint() and self._document_bucket():
            for item in self._s3_policy_objects():
                access = self._document_access_rows()
                access_by_title = {row.get("title"): row for row in access}
                allowed_roles = _split_roles((access_by_title.get(item["title"]) or {}).get("allowed_roles", "all_staff"))
                self._index_policy_document(item["title"], item["key"], allowed_roles)
            opensearch_hits = self._search_policy_opensearch(query, top_k, roles)
            if opensearch_hits:
                return {"query": query, "hits": opensearch_hits}
        if self._document_bucket():
            hits: list[dict[str, Any]] = []
            query_terms = _terms(query)
            query_vector = _term_vector(query)
            for item in self._s3_policy_objects():
                title = item["title"]
                if not self._document_allowed_for_roles(title, roles):
                    continue
                filename_score = sum(1 for term in query_terms if term in title.lower())
                text = self._s3_text_object(item["bucket"], item["key"])
                for chunk_index, chunk in enumerate(_chunks(text), start=1):
                    chunk_vector = _term_vector(chunk)
                    overlap_score = sum(1 for term in query_terms if term in chunk.lower())
                    similarity = _cosine_similarity(query_vector, chunk_vector)
                    score = (overlap_score * 3) + filename_score + similarity
                    if score:
                        hits.append(
                            {
                                "title": title,
                                "path": item["key"],
                                "score": score,
                                "page": None,
                                "chunk": chunk_index,
                                "snippet": chunk,
                                "text_extracted": True,
                                "retrieval_mode": "s3_chunked_fallback",
                            }
                        )
            hits.sort(key=lambda item: item["score"], reverse=True)
            if hits:
                return {"query": query, "hits": hits[:top_k]}

        policy_dir = self.data_dir / "policies"
        hits: list[dict[str, Any]] = []
        query_terms = _terms(query)
        query_vector = _term_vector(query)
        for path in sorted(policy_dir.glob("*")):
            if path.suffix.lower() not in {".txt", ".md", ".pdf"}:
                continue
            if not self._document_allowed_for_roles(path.name, roles):
                continue
            pages = _extract_text_pages(path)
            filename_score = sum(1 for term in query_terms if term in path.name.lower())
            for page in pages:
                for chunk_index, chunk in enumerate(_chunks(str(page["text"])), start=1):
                    chunk_vector = _term_vector(chunk)
                    overlap_score = sum(1 for term in query_terms if term in chunk.lower())
                    similarity = _cosine_similarity(query_vector, chunk_vector)
                    score = (overlap_score * 3) + filename_score + similarity
                    if score:
                        hits.append(
                            {
                                "title": path.name,
                                "path": str(path),
                                "score": score,
                                "page": page.get("page"),
                                "chunk": chunk_index,
                                "snippet": chunk,
                                "text_extracted": True,
                                "retrieval_mode": "chunked_local_embedding",
                            }
                        )
            if not pages and filename_score:
                hits.append(
                    {
                        "title": path.name,
                        "path": str(path),
                        "score": filename_score,
                        "page": None,
                        "chunk": None,
                        "snippet": f"Policy file: {path.name}. Text extraction is not available for this file.",
                        "text_extracted": False,
                        "retrieval_mode": "filename_fallback",
                    }
                )
        hits.sort(key=lambda item: item["score"], reverse=True)
        return {"query": query, "hits": hits[:top_k]}

    def list_policy_documents(self) -> dict[str, Any]:
        access_by_title = {row.get("title"): row for row in self._document_access_rows()}
        if self._document_bucket():
            return {
                "documents": [
                    {
                        "title": item["title"],
                        "path": "",
                        "allowed_roles": _split_roles((access_by_title.get(item["title"]) or {}).get("allowed_roles", "all_staff")),
                        "doc_type": "policy",
                        "s3_bucket": item["bucket"],
                        "s3_key": item["key"],
                        "uploaded_at": (access_by_title.get(item["title"]) or {}).get("uploaded_at", ""),
                    }
                    for item in self._s3_policy_objects()
                ]
            }
        policy_dir = self.data_dir / "policies"
        documents = [
            {
                "title": path.name,
                "path": str(path),
                "allowed_roles": _split_roles((access_by_title.get(path.name) or {}).get("allowed_roles", "all_staff")),
                "doc_type": "policy",
                "s3_bucket": (access_by_title.get(path.name) or {}).get("s3_bucket", ""),
                "s3_key": (access_by_title.get(path.name) or {}).get("s3_key", ""),
                "uploaded_at": (access_by_title.get(path.name) or {}).get("uploaded_at", ""),
            }
            for path in sorted(policy_dir.glob("*"))
            if path.suffix.lower() in {".txt", ".md", ".pdf"}
        ]
        return {"documents": documents}

    def upload_policy_document(
        self,
        *,
        filename: str,
        content: bytes,
        allowed_roles: list[str],
        s3_bucket: str | None = None,
    ) -> dict[str, Any]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        if not safe_name.lower().endswith((".pdf", ".txt", ".md")):
            raise ValueError("Only PDF, TXT, and MD documents are supported.")

        bucket = s3_bucket or os.getenv("POLICY_S3_BUCKET") or os.getenv("S3_BUCKET")
        s3_key = f"policies/{safe_name}"
        uploaded_to_s3 = False
        if bucket:
            self._s3_client().put_object(Bucket=bucket, Key=s3_key, Body=content)
            uploaded_to_s3 = True
        else:
            policy_dir = self.data_dir / "policies"
            policy_dir.mkdir(parents=True, exist_ok=True)
            (policy_dir / safe_name).write_bytes(content)

        self._upsert_document_access(
            title=safe_name,
            allowed_roles=allowed_roles or ["all_staff"],
            doc_type="policy",
            s3_bucket=bucket or "",
            s3_key=s3_key if uploaded_to_s3 else "",
            uploaded_at=__import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )
        if uploaded_to_s3:
            self._index_policy_document(safe_name, s3_key, allowed_roles or ["all_staff"], content)
        return {
            "title": safe_name,
            "path": "",
            "allowed_roles": allowed_roles or ["all_staff"],
            "s3_bucket": bucket or "",
            "s3_key": s3_key if uploaded_to_s3 else "",
            "uploaded_to_s3": uploaded_to_s3,
        }

    def list_lookup_csv_documents(self) -> dict[str, Any]:
        access_by_title = {row.get("title"): row for row in self._document_access_rows()}
        if self._document_bucket():
            return {
                "documents": [
                    {
                        "title": re.sub(r"[^A-Za-z0-9._-]+", "_", item["title"]),
                        "path": "",
                        "allowed_roles": _split_roles((access_by_title.get(item["title"]) or {}).get("allowed_roles", "all_staff")),
                        "doc_type": "lookup_csv",
                        "s3_bucket": item["bucket"],
                        "s3_key": item["key"],
                        "uploaded_at": (access_by_title.get(item["title"]) or {}).get("uploaded_at", ""),
                    }
                    for item in self._s3_csv_objects()
                ]
            }
        lookup_dir = self.data_dir / "lookups" / "phase1"
        documents_by_title = {}
        for path in sorted(lookup_dir.glob("*.csv")):
            documents_by_title[path.name] = {
                "title": path.name,
                "path": str(path),
                "allowed_roles": _split_roles((access_by_title.get(path.name) or {}).get("allowed_roles", "all_staff")),
                "doc_type": "lookup_csv",
                "s3_bucket": (access_by_title.get(path.name) or {}).get("s3_bucket", ""),
                "s3_key": (access_by_title.get(path.name) or {}).get("s3_key", ""),
                "uploaded_at": (access_by_title.get(path.name) or {}).get("uploaded_at", ""),
            }
        for item in self._s3_csv_objects():
            title = re.sub(r"[^A-Za-z0-9._-]+", "_", item["title"])
            if title in documents_by_title:
                documents_by_title[title]["s3_bucket"] = documents_by_title[title].get("s3_bucket") or item["bucket"]
                documents_by_title[title]["s3_key"] = documents_by_title[title].get("s3_key") or item["key"]
                continue
            documents_by_title[title] = {
                "title": title,
                "path": "",
                "allowed_roles": _split_roles((access_by_title.get(title) or {}).get("allowed_roles", "all_staff")),
                "doc_type": "lookup_csv",
                "s3_bucket": item["bucket"],
                "s3_key": item["key"],
                "uploaded_at": (access_by_title.get(title) or {}).get("uploaded_at", ""),
            }
        return {"documents": list(documents_by_title.values())}

    def upload_lookup_csv(
        self,
        *,
        filename: str,
        content: bytes,
        allowed_roles: list[str],
        s3_bucket: str | None = None,
    ) -> dict[str, Any]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        if not safe_name.lower().endswith(".csv"):
            raise ValueError("Only CSV lookup files are supported.")

        bucket = s3_bucket or self._document_bucket()
        s3_key = f"lookups/{safe_name}"
        uploaded_to_s3 = False
        if bucket:
            self._s3_client().put_object(Bucket=bucket, Key=s3_key, Body=content)
            uploaded_to_s3 = True
        else:
            lookup_dir = self.data_dir / "lookups" / "phase1"
            lookup_dir.mkdir(parents=True, exist_ok=True)
            (lookup_dir / safe_name).write_bytes(content)

        self._upsert_document_access(
            title=safe_name,
            allowed_roles=allowed_roles or ["all_staff"],
            doc_type="lookup_csv",
            s3_bucket=bucket or "",
            s3_key=s3_key if uploaded_to_s3 else "",
            uploaded_at=__import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )
        return {
            "title": safe_name,
            "path": "",
            "allowed_roles": allowed_roles or ["all_staff"],
            "s3_bucket": bucket or "",
            "s3_key": s3_key if uploaded_to_s3 else "",
            "uploaded_to_s3": uploaded_to_s3,
        }

    def update_policy_document_roles(self, title: str, allowed_roles: list[str]) -> dict[str, Any]:
        rows = self._document_access_rows()
        existing = None
        for row in rows:
            if row.get("title") == title:
                existing = row
                break
        if existing is None:
            existing = {
                "title": title,
                "doc_type": "policy" if not title.lower().endswith(".csv") else "lookup_csv",
                "s3_bucket": "",
                "s3_key": "",
                "uploaded_at": "",
            }
            rows.append(existing)
        existing["allowed_roles"] = _join_roles(allowed_roles)
        self._write_document_access_rows(rows)
        return {"title": title, "allowed_roles": allowed_roles}

    def get_guardian_nhs_news(self, limit: int = 10) -> dict[str, Any]:
        rows = self._rows("nhs_guardian_news.csv")
        return {"articles": rows[:limit]}

    # Deterministic lookup tools
    def lookup_doctor(self, query: str) -> dict[str, Any]:
        return {"matches": [row for row in self._rows("doctors.csv") if _contains(row, query)]}

    def lookup_department(self, query: str) -> dict[str, Any]:
        doctors = self._rows("doctors.csv")
        departments = {}
        for row in doctors:
            key = row.get("department", "")
            if key and query.lower() in key.lower():
                departments[key] = {"department": key, "doctors": []}
            if key in departments:
                departments[key]["doctors"].append(row)
        return {"matches": list(departments.values())}

    def lookup_appointment_slots(self, query: str = "") -> dict[str, Any]:
        rows = [
            row for row in self._rows("appointments.csv")
            if row.get("status") in {"booked", "rescheduled"} and (not query or _contains(row, query))
        ]
        return {"matches": rows}

    def lookup_availability(self, query: str = "") -> dict[str, Any]:
        query_terms = set(_terms(query))
        department_terms = query_terms & {
            "cardiology",
            "respiratory",
            "icu",
            "pharmacy",
            "maternity",
            "paediatrics",
            "oncology",
            "renal",
            "surgery",
            "radiology",
            "pathology",
            "mental",
            "community",
            "infection",
            "emergency",
        }
        role_terms = set()
        if query_terms & {"pharmacist", "pharmacy"}:
            role_terms.add("pharmacist")
            department_terms.add("pharmacy")
        if query_terms & {"doctor", "doctors", "consultant"}:
            role_terms.update({"consultant", "registrar", "physician"})
        if query_terms & {"nurse", "nurses", "nursing"}:
            role_terms.add("nurse")
        if "manager" in query_terms:
            role_terms.add("manager")

        rota_rows = []
        lookup_tables = dict(self._lookup_csv_tables())
        for row in lookup_tables.get("staff_rota.csv", []):
            text = " ".join(str(value).lower() for value in row.values())
            if department_terms and not any(term in text for term in department_terms):
                continue
            role_text = row.get("role", "").lower()
            if role_terms and not any(term in role_text for term in role_terms):
                continue
            if row.get("on_call", "").lower() == "yes" or {"available", "availability", "doctor", "consultant"} & query_terms:
                rota_rows.append(row)

        clinic_rows = []
        include_clinics = not role_terms or role_terms & {"consultant", "registrar", "physician", "pharmacist"}
        if include_clinics:
            for row in lookup_tables.get("appointment_clinics.csv", []):
                text = " ".join(str(value).lower() for value in row.values())
                if department_terms and not any(term in text for term in department_terms):
                    continue
                try:
                    slots_available = int(row.get("slots_available") or 0)
                except ValueError:
                    slots_available = 0
                if slots_available > 0:
                    clinic_rows.append(row)

        return {"staff_rota": rota_rows[:10], "appointment_clinics": clinic_rows[:10]}

    def lookup_nurse_in_charge(self, department: str = "ICU") -> dict[str, Any]:
        lookup_tables = dict(self._lookup_csv_tables())
        department_term = department.lower()
        staff_rows = []
        for row in lookup_tables.get("staff_rota.csv", []):
            if department_term not in row.get("department", "").lower():
                continue
            role_text = row.get("role", "").lower()
            if "nurse" not in role_text:
                continue
            staff_rows.append(row)

        contact_rows = []
        for row in lookup_tables.get("department_contacts.csv", []):
            if department_term not in row.get("department", "").lower():
                continue
            text = " ".join(str(value).lower() for value in row.values())
            if "nurse" in text or "staff absence" in text or "clinical" in text:
                contact_rows.append(row)

        staff_rows.sort(
            key=lambda row: (
                row.get("on_call", "").lower() != "yes",
                "charge" not in row.get("role", "").lower() and "senior" not in row.get("role", "").lower(),
                row.get("date", ""),
            )
        )
        return {"staff_rota": staff_rows[:5], "department_contacts": contact_rows[:5]}

    def lookup_patient_or_lab(self, query: str, patient_id: str | None = None, include_labs: bool = True) -> dict[str, Any]:
        lab_reports = self._rows("lab_reports.csv")
        if patient_id:
            lab_reports = [row for row in lab_reports if row.get("patient_id") == patient_id]
        report_ids = {row.get("report_id") for row in lab_reports}
        lab_results = self._rows("lab_results.csv")
        if patient_id:
            lab_results = [row for row in lab_results if row.get("report_id") in report_ids]
        return {
            "patients": [row for row in self._rows("patients.csv") if _contains(row, query)],
            "lab_reports": [row for row in lab_reports if include_labs and _contains(row, query)],
            "lab_results": [row for row in lab_results if include_labs and _contains(row, query)],
        }

    def search_phase1_lookup_tables(self, query: str, max_rows_per_table: int = 10) -> dict[str, Any]:
        matches: dict[str, list[dict[str, str]]] = {}
        query_terms = _terms(query)
        for title, rows in self._lookup_csv_tables():
            scored_rows = []
            for row in rows:
                score = _row_score(row, query_terms)
                if score:
                    scored_rows.append((score, row))
            if scored_rows:
                scored_rows.sort(key=lambda item: item[0], reverse=True)
                matches[title] = [row for _, row in scored_rows[:max_rows_per_table]]
        return {"matches": matches}

    def search_all_lookup_tables(
        self,
        query: str,
        max_rows_per_table: int = 10,
        excluded_tables: set[str] | None = None,
        patient_id: str | None = None,
        include_patient_labs: bool = False,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        excluded_tables = excluded_tables or set()
        table_names = [
            "patients.csv",
            "doctors.csv",
            "appointments.csv",
            "lab_reports.csv",
            "lab_results.csv",
        ]

        query_terms = _terms(query)
        matches: dict[str, dict[str, Any]] = {}
        patient_ids_from_query: set[str] = set()
        patient_lookup_terms: list[str] = []
        if include_patient_labs and not patient_id:
            patient_lookup_terms = [
                term for term in query_terms
                if term not in {"patient", "lab", "labs", "result", "results", "report", "reports", "show"}
            ]
            for patient in self._rows("patients.csv"):
                patient_text = " ".join(str(value).lower() for value in patient.values())
                if patient_lookup_terms and any(term in patient_text for term in patient_lookup_terms):
                    patient_ids_from_query.add(patient.get("patient_id", ""))
        unmatched_patient_lookup = (
            include_patient_labs
            and not patient_id
            and bool(patient_lookup_terms)
            and not patient_ids_from_query
        )
        patient_report_ids_from_query = {
            report.get("report_id")
            for report in self._rows("lab_reports.csv")
            if report.get("patient_id") in patient_ids_from_query
        }

        for table_name in table_names:
            if table_name in excluded_tables:
                continue
            if table_name in {"lab_reports.csv", "lab_results.csv"} and not include_patient_labs:
                continue
            scored_rows = []
            for row in self._rows(table_name):
                if unmatched_patient_lookup and table_name in {"lab_reports.csv", "lab_results.csv"}:
                    continue
                if table_name == "lab_reports.csv" and patient_id and row.get("patient_id") != patient_id:
                    continue
                if table_name == "lab_reports.csv" and not patient_id and patient_ids_from_query:
                    if row.get("patient_id") not in patient_ids_from_query:
                        continue
                if table_name == "lab_results.csv" and patient_id:
                    patient_report_ids = {
                        report.get("report_id")
                        for report in self._rows("lab_reports.csv")
                        if report.get("patient_id") == patient_id
                    }
                    if row.get("report_id") not in patient_report_ids:
                        continue
                if table_name == "lab_results.csv" and not patient_id and patient_report_ids_from_query:
                    if row.get("report_id") not in patient_report_ids_from_query:
                        continue
                if table_name == "equipment_assets.csv" and "ventilator" in query_terms:
                    if "ventilator" not in row.get("equipment_type", "").lower():
                        continue
                if table_name == "incident_categories.csv" and "severe" in query_terms:
                    if row.get("severity", "").lower() != "severe":
                        continue
                score = _row_score(row, query_terms)
                if not score and table_name == "lab_reports.csv" and patient_ids_from_query:
                    score = 1
                if not score and table_name == "lab_results.csv" and patient_report_ids_from_query:
                    score = 1
                if score:
                    scored_rows.append((score, row))
            if scored_rows:
                scored_rows.sort(key=lambda item: item[0], reverse=True)
                rows = [row for _, row in scored_rows]
                matches[table_name] = {
                    "total_matches": len(rows),
                    "rows": rows[:max_rows_per_table],
                    "columns": list(rows[0].keys()) if rows else [],
                }
        for title, rows_for_table in self._lookup_csv_tables():
            if title in excluded_tables:
                continue
            if not self._document_allowed_for_roles(title, roles):
                continue
            if title in {"lab_reports.csv", "lab_results.csv"} and not include_patient_labs:
                continue
            if unmatched_patient_lookup and title in {"lab_reports.csv", "lab_results.csv"}:
                continue
            scored_rows = []
            for row in rows_for_table:
                if title == "equipment_assets.csv" and "ventilator" in query_terms:
                    if "ventilator" not in row.get("equipment_type", "").lower():
                        continue
                if title == "incident_categories.csv" and "severe" in query_terms:
                    if row.get("severity", "").lower() != "severe":
                        continue
                score = _row_score(row, query_terms)
                if score:
                    scored_rows.append((score, row))
            if scored_rows:
                scored_rows.sort(key=lambda item: item[0], reverse=True)
                rows = [row for _, row in scored_rows]
                matches[title] = {
                    "total_matches": len(rows),
                    "rows": rows[:max_rows_per_table],
                    "columns": list(rows[0].keys()) if rows else [],
                }
        return {
            "query": query,
            "matches": matches,
            "unmatched_patient_lookup": unmatched_patient_lookup,
            "patient_lookup_terms": patient_lookup_terms,
        }

    # Patient portal tools
    def get_patient_profile(self, authenticated_patient_id: str) -> dict[str, Any]:
        for row in self._rows("patients.csv"):
            if row.get("patient_id") == authenticated_patient_id:
                return {"patient": row}
        return {"patient": None}

    def get_assigned_doctor(self, authenticated_patient_id: str) -> dict[str, Any]:
        profile = self.get_patient_profile(authenticated_patient_id).get("patient") or {}
        gp_name = profile.get("registered_gp", "")
        doctors = [row for row in self._rows("doctors.csv") if row.get("full_name") == gp_name]
        return {"doctor": doctors[0] if doctors else None}

    def get_patient_appointments(self, authenticated_patient_id: str) -> dict[str, Any]:
        rows = [row for row in self._rows("appointments.csv") if row.get("patient_id") == authenticated_patient_id]
        rows.sort(key=lambda row: (row.get("appointment_date", ""), row.get("appointment_time", "")))
        return {"appointments": rows}

    def book_patient_appointment(
        self,
        authenticated_patient_id: str,
        doctor_id: str,
        appointment_date: str,
        appointment_time: str,
        reason: str,
    ) -> dict[str, Any]:
        rows = self._rows("appointments.csv")
        appointment = {
            "appointment_id": "A" + uuid4().hex[:8].upper(),
            "patient_id": authenticated_patient_id,
            "doctor_id": doctor_id,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "appointment_type": "Patient requested appointment",
            "status": "booked",
            "location": "To be confirmed",
            "reason": reason,
        }
        rows.append(appointment)
        fieldnames = [
            "appointment_id",
            "patient_id",
            "doctor_id",
            "appointment_date",
            "appointment_time",
            "appointment_type",
            "status",
            "location",
            "reason",
        ]
        self._replace_db_rows("appointments.csv", rows, fieldnames)
        return {"appointment": appointment}

    def get_patient_lab_reports(self, authenticated_patient_id: str) -> dict[str, Any]:
        reports = [row for row in self._rows("lab_reports.csv") if row.get("patient_id") == authenticated_patient_id]
        reports.sort(key=lambda row: row.get("report_date", ""), reverse=True)
        return {"lab_reports": reports}

    def get_patient_lab_report_details(self, authenticated_patient_id: str, report_id: str) -> dict[str, Any]:
        reports = [
            row for row in self._rows("lab_reports.csv")
            if row.get("patient_id") == authenticated_patient_id and row.get("report_id") == report_id
        ]
        if not reports:
            return {"report": None, "results": []}
        results = [row for row in self._rows("lab_results.csv") if row.get("report_id") == report_id]
        return {"report": reports[0], "results": results}

    def summarise_lab_reports(self, authenticated_patient_id: str, max_reports: int = 3) -> dict[str, Any]:
        reports = self.get_patient_lab_reports(authenticated_patient_id)["lab_reports"][:max_reports]
        all_results = self._rows("lab_results.csv")
        report_ids = {report["report_id"] for report in reports}
        results = [row for row in all_results if row.get("report_id") in report_ids]
        abnormal = [row for row in results if row.get("flag") not in {"", "normal"}]
        normal_count = len(results) - len(abnormal)
        lines = []
        if abnormal:
            lines.append("Some recent results are outside the usual reference range.")
            for row in abnormal[:6]:
                lines.append(
                    f"{row.get('test_name')} was {row.get('flag')} at {row.get('value')} {row.get('unit')} "
                    f"(usual range: {row.get('reference_range')})."
                )
        else:
            lines.append("The recent lab results in this demo data are within the listed reference ranges.")
        if normal_count:
            lines.append(f"{normal_count} result(s) were marked as within the usual range.")
        lines.append(
            "This is a simple explanation, not a diagnosis. Please discuss questions or symptoms with your clinician."
        )
        return {"summary": " ".join(lines), "reports": reports, "abnormal_results": abnormal}


def _zed_data_dir() -> Path:
    configured = os.getenv("ZED_HEALTH_DATA_DIR") or os.getenv("DATA_DIR")
    if configured:
        return Path(configured)
    return Path("/tmp/zed-healthcare-empty-data")


def _roles(payload: dict[str, Any]) -> list[str]:
    roles = payload.get("roles")
    if isinstance(roles, list):
        return [str(role) for role in roles if str(role).strip()]
    user_context = payload.get("user_context")
    if isinstance(user_context, dict) and isinstance(user_context.get("roles"), list):
        return [str(role) for role in user_context["roles"] if str(role).strip()]
    return []


class ZedHealthcareTools:
    """MCP adapter for the ZED Healthcare tool implementation."""

    def __init__(self, tools: HealthcareTools):
        self.tools = tools

    @classmethod
    def from_env(cls) -> "ZedHealthcareTools":
        return cls(HealthcareTools.from_data_dir(_zed_data_dir()))

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
