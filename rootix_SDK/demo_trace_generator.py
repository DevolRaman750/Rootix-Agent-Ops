import argparse
import json
import random
import time
import uuid

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from rootix_SDK import flush, initialize, observe


tracer = trace.get_tracer("rootix-sdk-demo")


def _add_log(level: str, message: str, **fields) -> None:
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return
    attributes = {"log.level": level, "log.message": message}
    for key, value in fields.items():
        attributes[f"log.{key}"] = str(value)
    span.add_event("app.log", attributes=attributes)


def _sleep_ms(min_ms: int, max_ms: int) -> None:
    time.sleep(random.uniform(min_ms, max_ms) / 1000.0)


@observe(name="agent.route_request", type="agent")
def route_request(prompt: str) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "AGENT")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps({"component": "router", "operation": "route_request"}),
    )
    _add_log("INFO", "Routing request", prompt_preview=prompt[:60])
    _sleep_ms(20, 80)

    route = "chat"
    if "sql" in prompt.lower() or "report" in prompt.lower():
        route = "analytics"
    if "deploy" in prompt.lower() or "incident" in prompt.lower():
        route = "ops"

    _add_log("INFO", "Route selected", route=route)
    return {"route": route}


@observe(name="tool.fetch_context", type="tool")
def fetch_context(route: str, prompt: str) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "TOOL")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps({"component": "retriever", "route": route}),
    )
    _add_log("DEBUG", "Fetching context", route=route)
    _sleep_ms(40, 140)

    docs = [
        {"id": "doc-101", "score": 0.91, "title": "Runbook: API Latency"},
        {"id": "doc-044", "score": 0.84, "title": "Playbook: Release Rollback"},
        {"id": "doc-210", "score": 0.79, "title": "Policy: Access Control"},
    ]
    picked = docs[: random.randint(1, 3)]

    _add_log("INFO", "Context fetched", doc_count=len(picked))
    return {"route": route, "prompt": prompt, "documents": picked}


@observe(name="tool.guardrail_check", type="tool")
def guardrail_check(prompt: str) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "TOOL")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps({"component": "guardrail", "policy_version": "v1"}),
    )
    _sleep_ms(15, 60)

    blocked_terms = ["password dump", "prod secrets"]
    lowered = prompt.lower()
    blocked = any(term in lowered for term in blocked_terms)
    _add_log("INFO", "Guardrail evaluated", blocked=blocked)
    return {"blocked": blocked}


@observe(name="llm.generate_response", type="llm")
def generate_response(prompt: str, context: dict) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "LLM")
    span.set_attribute("rootix.llm.model", "gpt-4.1-mini")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps(
            {
                "component": "llm",
                "route": context["route"],
                "doc_count": len(context["documents"]),
            }
        ),
    )

    input_tokens = random.randint(320, 1200)
    output_tokens = random.randint(80, 420)
    total_tokens = input_tokens + output_tokens
    span.set_attribute("llm.token_count.prompt", input_tokens)
    span.set_attribute("llm.token_count.completion", output_tokens)
    span.set_attribute("llm.token_count.total", total_tokens)

    _add_log("INFO", "Calling model", model="gpt-4.1-mini", input_tokens=input_tokens)
    _sleep_ms(120, 420)

    response = (
        f"Route={context['route']}. Based on {len(context['documents'])} docs, "
        f"recommended action: validate assumptions, run safe checks, then proceed."
    )
    _add_log("INFO", "Model response received", output_tokens=output_tokens)
    return {
        "text": response,
        "confidence": round(random.uniform(0.71, 0.97), 2),
    }


@observe(name="agent.compose_final", type="agent")
def compose_final(context: dict, llm_result: dict) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "AGENT")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps({"component": "composer", "citations": len(context["documents"])}),
    )
    _sleep_ms(20, 75)
    _add_log("INFO", "Composing final response")

    return {
        "summary": llm_result["text"],
        "citations": [doc["id"] for doc in context["documents"]],
        "confidence": llm_result["confidence"],
    }


@observe(name="tool.publish_result", type="tool")
def publish_result(trace_name: str, result: dict) -> dict:
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "TOOL")
    span.set_attribute(
        "traceroot.span.metadata",
        json.dumps({"component": "publisher", "target": "ui"}),
    )
    _sleep_ms(10, 40)
    _add_log("INFO", "Publishing result", trace_name=trace_name)
    return {"status": "published", "trace": trace_name, "chars": len(result["summary"])}


def run_demo_traces(count: int = 8) -> None:
    prompts = [
        "Investigate API latency spike after last deployment",
        "Generate weekly SQL report for signup conversion",
        "Help draft customer-facing incident update",
        "Plan rollback sequence for failed production release",
        "Summarize auth errors by region and likely causes",
        "Recommend canary strategy for payment service",
        "Create postmortem outline from current outage timeline",
        "Suggest database optimization for slow dashboard queries",
    ]

    for i in range(count):
        prompt = prompts[i % len(prompts)]
        user_id = f"user-{(i % 4) + 1}"
        session_id = f"sess-{uuid.uuid4().hex[:10]}"
        trace_name = f"demo.trace.{i + 1:02d}"

        with tracer.start_as_current_span(trace_name) as root:
            root.set_attribute("traceroot.span.type", "AGENT")
            root.set_attribute("rootix.trace.user_id", user_id)
            root.set_attribute("rootix.trace.session_id", session_id)
            root.set_attribute("rootix.environment", "local-demo")
            _add_log("INFO", "Trace started", trace_name=trace_name, user_id=user_id)

            try:
                route = route_request(prompt)
                guardrail = guardrail_check(prompt)

                if guardrail.get("blocked"):
                    _add_log("WARN", "Request blocked by guardrail")
                    root.set_status(Status(StatusCode.ERROR, "Blocked by guardrail"))
                    continue

                context = fetch_context(route=route["route"], prompt=prompt)
                llm_result = generate_response(prompt=prompt, context=context)

                # Inject one realistic failure trace for UI testing.
                if i == count - 2:
                    raise RuntimeError("Downstream publish timeout (simulated)")

                final = compose_final(context=context, llm_result=llm_result)
                publish_result(trace_name=trace_name, result=final)
                root.set_status(Status(StatusCode.OK))
                _add_log("INFO", "Trace completed", trace_name=trace_name)
            except Exception as exc:
                root.record_exception(exc)
                root.set_status(Status(StatusCode.ERROR, str(exc)))
                _add_log("ERROR", "Trace failed", error=str(exc), trace_name=trace_name)

    flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate realistic demo traces via rootix_SDK and send to ingestion API."
    )
    parser.add_argument("--count", type=int, default=8, help="Number of top-level traces to emit")
    parser.add_argument(
        "--endpoint",
        type=str,
        default="http://localhost:8000/v1/traces",
        help="OTLP ingestion endpoint",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="demo-local-key",
        help="API key sent in Authorization header",
    )
    args = parser.parse_args()

    initialize(api_key=args.api_key, endpoint=args.endpoint)
    run_demo_traces(count=args.count)


if __name__ == "__main__":
    main()
