import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

def initialize(api_key: str = None, endpoint: str = "http://localhost:8000/v1/traces"):
    api_key = api_key or os.getenv("ROOTIX_API_KEY")
    
    resource = Resource.create({"service.name": "my-agent-service"})
    provider = TracerProvider(resource=resource)
    
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers={"Authorization": f"Bearer {api_key}"}
    )
    
    # Batch processor sends traces in chunks asynchronously
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

def flush():
    trace.get_tracer_provider().force_flush()
