import gzip
import logging
import uuid
from datetime import datetime, UTC
from fastapi import APIRouter, HTTPException, Query, Request
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from pydantic import BaseModel

from db.clickhouse.client import get_clickhouse_client
from rest.services.s3 import get_s3_service
from worker.ingest_tasks import process_s3_traces

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/traces")




def decode_otlp_protobuf(data: bytes) -> dict:
    """Decodes OpenTelemetry Protobuf to standard camelCase JSON."""
    request = ExportTraceServiceRequest()
    request.ParseFromString(data)
    return MessageToDict(request)

class IngestResponse(BaseModel):
    """Response for trace ingestion."""

    status: str
    file_key: str


class TraceListItem(BaseModel):
    id: str
    status: str
    model: str
    user_id: str
    latency: int
    tokens: int
    cost: float
    timestamp: str
    name: str
    span_count: int


class TraceListResponse(BaseModel):
    items: list[TraceListItem]
    total: int


class SpanItem(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    span_kind: str
    status: str
    span_start_time: str
    span_end_time: str | None
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    input: str | None = None
    output: str | None = None
    metadata: str | None = None
    status_message: str | None = None


class SpanListResponse(BaseModel):
    items: list[SpanItem]


def _to_iso(value) -> str:
    """Convert clickhouse datetime-like value to ISO string."""
    if value is None:
        return datetime.now(UTC).isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.get("", response_model=TraceListResponse)
async def list_traces(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Fetch trace summaries for the Trace Explorer UI."""
    project_id = "proj_123"
    ch = get_clickhouse_client()

    traces_query = """
    SELECT
        t.trace_id AS id,
        multiIf(
            countIf(upper(s.status) = 'ERROR') > 0,
            'ERROR',
            countIf(upper(s.status) = 'RUNNING') > 0,
            'RUNNING',
            'SUCCESS'
        ) AS status,
        ifNull(any(s.model_name), 'unknown') AS model,
        ifNull(t.user_id, '') AS user_id,
        toInt64(
            if(
                count(s.span_id) = 0,
                0,
                dateDiff(
                    'millisecond',
                    min(ifNull(s.span_start_time, t.trace_start_time)),
                    max(ifNull(s.span_end_time, ifNull(s.span_start_time, t.trace_start_time)))
                )
            )
        ) AS latency,
        toInt64(sum(ifNull(s.total_tokens, 0))) AS tokens,
        toFloat64(sum(ifNull(s.cost, 0))) AS cost,
        t.trace_start_time AS timestamp,
        t.name AS name,
        toInt64(count(s.span_id)) AS span_count
    FROM traces t
    LEFT JOIN spans s ON s.trace_id = t.trace_id AND s.project_id = t.project_id
    WHERE t.project_id = {project_id:String}
    GROUP BY t.trace_id, t.user_id, t.trace_start_time, t.name
    ORDER BY t.trace_start_time DESC
    LIMIT {limit:UInt32} OFFSET {offset:UInt32}
    """

    total_query = """
    SELECT count() AS total
    FROM traces
    WHERE project_id = {project_id:String}
    """

    traces_result = ch.query(
        traces_query,
        parameters={"project_id": project_id, "limit": limit, "offset": offset},
    )
    total_result = ch.query(total_query, parameters={"project_id": project_id})

    items: list[TraceListItem] = []
    for row in traces_result.named_results():
        items.append(
            TraceListItem(
                id=str(row.get("id", "")),
                status=str(row.get("status", "SUCCESS")),
                model=str(row.get("model", "unknown")),
                user_id=str(row.get("user_id", "")),
                latency=int(row.get("latency", 0) or 0),
                tokens=int(row.get("tokens", 0) or 0),
                cost=float(row.get("cost", 0.0) or 0.0),
                timestamp=_to_iso(row.get("timestamp")),
                name=str(row.get("name", "Trace")),
                span_count=int(row.get("span_count", 0) or 0),
            )
        )

    total = int(total_result.result_rows[0][0]) if total_result.result_rows else 0
    return TraceListResponse(items=items, total=total)


@router.get("/{trace_id}/spans", response_model=SpanListResponse)
async def list_trace_spans(trace_id: str):
    """Fetch all spans for a trace to build the waterfall tree."""
    project_id = "proj_123"
    ch = get_clickhouse_client()

    spans_query = """
    SELECT
        span_id,
        trace_id,
        parent_span_id,
        name,
        span_kind,
        upper(status) AS status,
        span_start_time,
        span_end_time,
        model_name,
        input_tokens,
        output_tokens,
        total_tokens,
        toFloat64(ifNull(cost, 0)) AS cost,
        input,
        output,
        metadata,
        status_message
    FROM spans FINAL
    WHERE project_id = {project_id:String} AND trace_id = {trace_id:String}
    ORDER BY span_start_time ASC
    """

    spans_result = ch.query(
        spans_query,
        parameters={"project_id": project_id, "trace_id": trace_id},
    )

    items: list[SpanItem] = []
    for row in spans_result.named_results():
        items.append(
            SpanItem(
                span_id=str(row.get("span_id", "")),
                trace_id=str(row.get("trace_id", "")),
                parent_span_id=row.get("parent_span_id"),
                name=str(row.get("name", "span")),
                span_kind=str(row.get("span_kind", "SPAN")),
                status=str(row.get("status", "OK")),
                span_start_time=_to_iso(row.get("span_start_time")),
                span_end_time=_to_iso(row.get("span_end_time")) if row.get("span_end_time") else None,
                model_name=row.get("model_name"),
                input_tokens=int(row.get("input_tokens", 0)) if row.get("input_tokens") is not None else None,
                output_tokens=int(row.get("output_tokens", 0)) if row.get("output_tokens") is not None else None,
                total_tokens=int(row.get("total_tokens", 0)) if row.get("total_tokens") is not None else None,
                cost=float(row.get("cost", 0.0)) if row.get("cost") is not None else None,
                input=row.get("input"),
                output=row.get("output"),
                metadata=row.get("metadata"),
                status_message=row.get("status_message"),
            )
        )

    return SpanListResponse(items=items)

@router.post("")
async def ingest_traces(request: Request):
    """Ingest OTLP trace data sent by Python/JS SDKs."""
    
    # 1. AUTHENTICATION
    # (Extract 'Authorization: Bearer <key>' from request headers)
    # Validate key against DB to get project_id. Let's assume project_id="proj_123"
    project_id = "proj_123"
    
    # 2. READ & DECOMPRESS
    body = await request.body()
    if "gzip" in request.headers.get("content-encoding", "").lower():
        body = gzip.decompress(body)
        
    # 3. DECODE PROTOBUF TO JSON
    try:
        trace_json = decode_otlp_protobuf(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid OTLP protobuf format")
        
    # 4. GENERATE S3 BUCKET PATH (Time partitioned)
    now = datetime.now(UTC)
    s3_key = f"events/otel/{project_id}/{now.year}/{now.month}/{now.day}/{now.hour}/{uuid.uuid4()}.json"
    
    # 5. UPLOAD TO BLOB STORAGE (MinIO / S3)
    s3_service = get_s3_service()
    s3_service.upload_json(s3_key, trace_json)
    
    # 6. ENQUEUE CELERY TASK
    # Hand off the heavy ClickHouse insertion to a background worker
    process_s3_traces.delay(s3_key=s3_key, project_id=project_id)
    
    return {"status": "ok", "file_key": s3_key}