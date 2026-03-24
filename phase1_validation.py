from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"


@dataclass
class CheckResult:
    name: str
    status: str
    details: str


def ok(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, status="PASS", details=details)


def fail(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, status="FAIL", details=details)


def warn(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, status="WARN", details=details)


def run_protobuf_decode_check() -> CheckResult:
    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    ss = rs.scope_spans.add()
    span = ss.spans.add()
    span.trace_id = bytes.fromhex("00112233445566778899aabbccddeeff")
    span.span_id = bytes.fromhex("0011223344556677")
    span.name = "phase1-test-span"
    span.start_time_unix_nano = 1710000000000000000
    span.end_time_unix_nano = 1710000001000000000

    payload = req.SerializeToString()
    decoded = ExportTraceServiceRequest()
    decoded.ParseFromString(payload)
    data = MessageToDict(decoded)

    try:
        span_name = data["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"]
    except Exception as exc:
        return fail(
            "OTLP protobuf decode",
            f"Could not decode serialized OTLP payload to JSON-like dict: {exc}",
        )

    if span_name != "phase1-test-span":
        return fail(
            "OTLP protobuf decode",
            "Decoded payload did not preserve the span name as expected.",
        )

    return ok("OTLP protobuf decode", "Serialized OTLP protobuf decoded successfully via MessageToDict.")


def run_router_import_check() -> CheckResult:
    sys.path.insert(0, str(BACKEND))
    try:
        __import__("rest.routers.traces")
    except Exception as exc:
        return fail("Ingestion router import", f"rest.routers.traces cannot be imported: {exc}")
    finally:
        if str(BACKEND) in sys.path:
            sys.path.remove(str(BACKEND))

    return ok("Ingestion router import", "Router module imports correctly.")


def run_api_entrypoint_check() -> CheckResult:
    main_path = BACKEND / "rest" / "main.py"
    src = main_path.read_text(encoding="utf-8")
    if not src.strip():
        return fail("API entrypoint readiness", "backend/rest/main.py is empty.")

    required = ["FastAPI", "include_router", "routers.traces"]
    missing = [item for item in required if item not in src]
    if missing:
        return fail(
            "API entrypoint readiness",
            f"main.py is missing required app wiring signals: {', '.join(missing)}",
        )

    return ok("API entrypoint readiness", "FastAPI app appears wired with traces router.")


def run_router_wiring_static_check() -> CheckResult:
    traces_path = BACKEND / "rest" / "routers" / "traces.py"
    src = traces_path.read_text(encoding="utf-8")

    required_signals = [
        "decode_otlp_protobuf",
        "s3_service.upload_json(",
        "process_s3_traces.delay(",
        "content-encoding",
        "gzip.decompress",
    ]
    missing = [s for s in required_signals if s not in src]
    if missing:
        return fail(
            "Ingestion route static wiring",
            f"Missing expected ingestion flow signals: {', '.join(missing)}",
        )

    return ok(
        "Ingestion route static wiring",
        "Route contains decode, gzip handling, S3 upload, and Celery enqueue calls.",
    )


def _extract_sql_columns(sql_path: Path) -> set[str]:
    sql = sql_path.read_text(encoding="utf-8")
    in_create = False
    cols: set[str] = set()
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CREATE TABLE"):
            in_create = True
            continue
        if not in_create:
            continue
        if stripped.startswith(")"):
            break
        if not stripped or stripped.startswith("--"):
            continue
        m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\s+", stripped)
        if m:
            cols.add(m.group(1))
    return cols


def _extract_insert_columns_from_ast(py_path: Path, table_name: str) -> set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "insert":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or first.value != table_name:
            continue

        for kw in node.keywords:
            if kw.arg == "column_names" and isinstance(kw.value, ast.List):
                for item in kw.value.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        found.add(item.value)
    return found


def run_clickhouse_schema_compat_check() -> CheckResult:
    traces_sql_cols = _extract_sql_columns(BACKEND / "db" / "migrations" / "001_create_traces.sql")
    spans_sql_cols = _extract_sql_columns(BACKEND / "db" / "migrations" / "002_create_spans.sql")

    client_path = BACKEND / "db" / "clickhouse" / "client.py"
    traces_insert_cols = _extract_insert_columns_from_ast(client_path, "traces")
    spans_insert_cols = _extract_insert_columns_from_ast(client_path, "spans")

    trace_missing = sorted(c for c in traces_insert_cols if c not in traces_sql_cols)
    span_missing = sorted(c for c in spans_insert_cols if c not in spans_sql_cols)

    detail = {
        "traces_insert_columns": sorted(traces_insert_cols),
        "spans_insert_columns": sorted(spans_insert_cols),
        "trace_cols_missing_in_schema": trace_missing,
        "span_cols_missing_in_schema": span_missing,
    }

    if trace_missing or span_missing:
        return fail("ClickHouse schema compatibility", json.dumps(detail, indent=2))

    return ok("ClickHouse schema compatibility", "Insert column names are present in SQL schemas.")


def run_s3_service_behavior_check() -> CheckResult:
    class FakeBody:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

    class FakeS3Client:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
            self.objects[f"{Bucket}/{Key}"] = Body

        def get_object(self, *, Bucket: str, Key: str):
            body = self.objects[f"{Bucket}/{Key}"]
            return {"Body": FakeBody(body)}

    sys.path.insert(0, str(BACKEND))
    try:
        from rest.services.s3 import S3Service

        svc = S3Service(bucket_name="traceroot-test")
        fake = FakeS3Client()
        svc._client = fake

        key = "events/otel/proj_123/2026/3/23/10/test.json"
        data = {"resourceSpans": [{"scopeSpans": []}]}
        svc.upload_json(key, data)
        downloaded = svc.download_json(key)
    except Exception as exc:
        return fail("S3/MinIO JSON storage behavior", f"Upload/download check failed: {exc}")
    finally:
        if str(BACKEND) in sys.path:
            sys.path.remove(str(BACKEND))

    if downloaded != data:
        return fail(
            "S3/MinIO JSON storage behavior",
            "Downloaded payload does not match uploaded JSON payload.",
        )

    return ok("S3/MinIO JSON storage behavior", "S3 service correctly serializes and deserializes JSON.")


def run_sdk_wrapper_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    sdk_dir = ROOT / "rootix-SDK"
    dec_path = sdk_dir / "decorators.py"
    src = dec_path.read_text(encoding="utf-8")

    # Folder naming check for package importability.
    if "-" in sdk_dir.name:
        results.append(
            warn(
                "SDK package folder naming",
                "Folder rootix-SDK contains a hyphen, which is not importable as a normal Python package name.",
            )
        )
    else:
        results.append(ok("SDK package folder naming", "SDK folder name is import-friendly."))

    required_attrs = [
        "rootix.span.input",
        "rootix.span.output",
        "rootix.git.ref",
        "rootix.git.repo",
        "rootix.git.source_file",
        "rootix.git.source_line",
        "rootix.git.source_function",
    ]
    missing = [a for a in required_attrs if a not in src]
    if missing:
        results.append(
            fail("SDK @observe attribute capture", f"Missing expected attributes in decorator: {missing}")
        )
    else:
        results.append(
            ok(
                "SDK @observe attribute capture",
                "Decorator contains expected input/output and git metadata attribute capture logic.",
            )
        )

    if "traceback.format_exc()" in src and "span.record_exception(e)" in src:
        results.append(ok("SDK error capture", "Decorator records exceptions and stores traceback output."))
    else:
        results.append(
            fail(
                "SDK error capture",
                "Decorator does not appear to fully capture exception details.",
            )
        )

    return results


def run_phase1_checks() -> dict[str, Any]:
    checks: list[CheckResult] = []

    checks.append(run_protobuf_decode_check())
    checks.append(run_api_entrypoint_check())
    checks.append(run_router_import_check())
    checks.append(run_router_wiring_static_check())
    checks.append(run_s3_service_behavior_check())
    checks.append(run_clickhouse_schema_compat_check())
    checks.extend(run_sdk_wrapper_checks())

    summary = {
        "pass": sum(1 for c in checks if c.status == "PASS"),
        "fail": sum(1 for c in checks if c.status == "FAIL"),
        "warn": sum(1 for c in checks if c.status == "WARN"),
    }

    return {
        "summary": summary,
        "checks": [asdict(c) for c in checks],
    }


if __name__ == "__main__":
    result = run_phase1_checks()
    print(json.dumps(result, indent=2))
