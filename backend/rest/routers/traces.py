import gzip
import logging
import uuid
from datetime import datetime, UTC
from fastapi import APIRouter, HTTPException, Request
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from pydantic import BaseModel

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