import inspect
import json
import traceback
from functools import wraps
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .git_utils import get_git_ref, get_git_repo

tracer = trace.get_tracer("rootix-SDK")

def observe(name: str = None, type: str = "span"):
    def decorator(func):
        # Auto-extract function name if not provided
        span_name = name or func.__name__
        # Auto-extract the file and line number where this function is defined
        source_file = inspect.getsourcefile(func)
        try:
            source_line = inspect.getsourcelines(func)[1]
        except Exception:
            source_line = 0

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create a new OTEL Span
            with tracer.start_as_current_span(span_name) as span:
                # 1. Attach exact Rootix Attributes
                span.set_attribute("rootix.span.type", type.upper())
                
                # 2. Attach Git Context (For the AI Debugger's RCA via GitHub)
                git_ref = get_git_ref()
                if git_ref:
                    span.set_attribute("rootix.git.ref", git_ref)
                    span.set_attribute("rootix.git.repo", get_git_repo())
                span.set_attribute("rootix.git.source_file", str(source_file))
                span.set_attribute("rootix.git.source_line", source_line)
                span.set_attribute("rootix.git.source_function", func.__name__)

                # 3. Capture Inputs
                # Convert args/kwargs to a dict using inspect
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                try:
                    span.set_attribute("rootix.span.input", json.dumps(bound_args.arguments, default=str))
                except Exception:
                    pass

                try:
                    # Execute the actual function
                    result = func(*args, **kwargs)
                    
                    # 4. Capture Outputs
                    try:
                        span.set_attribute("rootix.span.output", json.dumps(result, default=str))
                    except Exception:
                        span.set_attribute("rootix.span.output", str(result))
                        
                    span.set_status(Status(StatusCode.OK))
                    return result
                    
                except Exception as e:
                    # 5. Capture Errors
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute("rootix.span.output", traceback.format_exc())
                    raise  # Re-raise the error so the user's app still crashes normally

        return wrapper
    return decorator
