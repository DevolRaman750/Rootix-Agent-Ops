# Phase 1 Test Plan and Execution Report

## Scope
This report covers Phase 1 validation for:
- Ingestion API behavior
- OTLP protobuf decode path
- JSON upload to object storage path
- Celery enqueue path
- ClickHouse schema compatibility
- SDK decorator behavior
- End-to-end full pipeline readiness

## Test Plan
1. Environment readiness
- Validate dependency installation in virtual environment
- Validate container orchestration configuration
- Start local infra services (ClickHouse, MinIO, Redis, Postgres)

2. Ingestion API tests
- Verify OTLP protobuf payload can be decoded to JSON structure
- Verify gzip compressed payload handling
- Verify object storage upload call is present and uses generated key path
- Verify Celery task enqueue call is present and passes s3_key and project_id
- Verify API entrypoint is runnable and routes are registered

3. Storage and queue tests
- Verify S3 service can serialize and deserialize JSON payloads
- Verify Celery worker can consume queued task (requires running Redis and worker)

4. ClickHouse tests
- Validate migration SQL schema exists for traces and spans
- Validate inserted column names in client match schema columns
- Validate real insert/query behavior (requires running ClickHouse)

5. SDK wrapper tests
- Validate decorator captures input/output fields
- Validate decorator captures git metadata fields
- Validate decorator captures errors and traceback
- Validate export path from SDK to ingestion API endpoint

6. Full pipeline tests
- Send OTLP payload to API
- Confirm JSON file exists in MinIO/S3
- Confirm Celery task is queued and processed
- Confirm trace and span rows appear in ClickHouse

## Executed Tests
Executed via [phase1_validation.py](phase1_validation.py).

Summary:
- PASS: 6
- FAIL: 2
- WARN: 1

Passes:
1. OTLP protobuf decode
2. Ingestion route static wiring (decode, gzip, S3 upload, Celery enqueue)
3. S3/MinIO JSON storage behavior (serialization/deserialization)
4. ClickHouse schema compatibility (insert columns align with migration schema)
5. SDK observe attribute capture
6. SDK error capture

Failures:
1. API entrypoint readiness
- [backend/rest/main.py](backend/rest/main.py) is empty.

2. Ingestion router import
- [backend/rest/routers/traces.py](backend/rest/routers/traces.py) imports [services.s3](backend/rest/services/s3.py) with an invalid module path.
- Current import uses: from services.s3 import get_s3_service
- This fails when importing router under backend package context.

Warnings:
1. SDK package folder naming
- [rootix-SDK](rootix-SDK) contains a hyphen, which is not import-friendly as a Python package name.

## Full End-to-End Pipeline Status
Not fully executable yet due infrastructure/runtime blockers:
1. Docker daemon unavailable on host at test time.
2. API app entrypoint not wired.
3. Router import path issue blocks app startup.

Because of these blockers, runtime verification of:
- API request handling
- MinIO object persistence through real service
- Celery queue and worker processing
- ClickHouse real inserts from worker
could not be completed in this run.

## Required Fixes Before Final E2E Retest
1. Implement app bootstrap in [backend/rest/main.py](backend/rest/main.py) with FastAPI app and router inclusion.
2. Fix imports in [backend/rest/routers/traces.py](backend/rest/routers/traces.py) to package-correct paths.
3. Ensure Docker Desktop daemon is running, then start compose services.
4. Start API and Celery worker processes, then run E2E ingest test payload.

## Retest Checklist (after fixes)
1. Start infra: docker compose up -d
2. Start API server and verify health endpoint
3. Start Celery worker and verify connection to Redis
4. Send OTLP protobuf payload to /v1/traces
5. Assert object exists in MinIO bucket traceroot
6. Assert Celery task executes successfully
7. Assert traces and spans rows exist in ClickHouse
