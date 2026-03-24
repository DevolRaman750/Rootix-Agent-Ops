"""FastAPI REST API server for Rootix.

This server currently handles OTEL trace ingestion for the Phase 1 pipeline.
"""

import os

from dotenv import load_dotenv

# Load environment variables from .env file before app imports settings.
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rest.routers.traces import router as traces_router
from shared.config import settings

app = FastAPI(
	title="Rootix API",
	description="Observability platform for LLM applications",
	version="0.1.0",
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=settings.cors_origins,
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

# Public ingestion API for SDKs.
app.include_router(traces_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
	"""Health check endpoint."""
	return {"status": "ok"}


if __name__ == "__main__":
	host = os.getenv("HOST", "0.0.0.0")
	port = int(os.getenv("PORT", "8000"))
	uvicorn.run(
		"rest.main:app",
		host=host,
		port=port,
	)
