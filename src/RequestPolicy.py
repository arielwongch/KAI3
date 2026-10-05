"""Bounded, observable retries for transient provider failures."""
from contextvars import ContextVar
import random
import re
import time
from openai import APIConnectionError, APITimeoutError

cancel_event = ContextVar('request_cancel_event', default=None)

class RequestCancelled(RuntimeError):
    pass


def status_code(error):
    code = getattr(error, 'status_code', None)
    if code is not None:
        return code
    match = re.search(r'Error code: (\d{3})', str(error))
    return int(match.group(1)) if match else None


def fatal_provider_error(error):
    return status_code(error) in (400, 401, 402, 403, 422)


def completion(api_client, diagnostics=None, phase='answer', **kwargs):
    metrics = diagnostics if diagnostics is not None else {}
    event = cancel_event.get()
    started = time.perf_counter()
    try:
        for attempt in range(5):
            if event is not None and event.is_set():
                raise RequestCancelled('Run cancelled.')
            metrics[phase + '_llm_calls'] = metrics.get(phase + '_llm_calls', 0) + 1
            try:
                return api_client.with_options(max_retries=0, timeout=180).chat.completions.create(**kwargs)
            except Exception as error:
                retryable = status_code(error) in (408, 429, 500, 502, 503, 504) or isinstance(error, (APIConnectionError, APITimeoutError))
                if not retryable or attempt == 4:
                    raise
                delay = min(60., 2 ** (attempt + 1) + random.random())
                headers = getattr(getattr(error, 'response', None), 'headers', {})
                try:
                    delay = max(delay, min(60., float(headers.get('retry-after', 0))))
                except (ValueError, TypeError):
                    pass
                metrics.setdefault(phase + '_retries', []).append(dict(status_code=status_code(error), delay_seconds=delay))
                if event is not None:
                    if event.wait(delay):
                        raise RequestCancelled('Run cancelled during retry wait.')
                else:
                    time.sleep(delay)
    finally:
        metrics[phase + '_seconds'] = time.perf_counter() - started
