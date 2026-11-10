"""Bounded, observable retries for transient provider failures."""
from contextvars import ContextVar
import random
import re
import time

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
    from Diagnostics import collector
    provenance = diagnostics if diagnostics is not None else collector.get()
    from ExperimentRecording import capture, sha256, operation, checkpoint
    # Only application request fields; never client objects, headers or credentials.
    payload = {k: kwargs[k] for k in ('model', 'messages', 'max_tokens', 'stream',
        'reasoning_effort', 'extra_body', 'response_format', 'temperature', 'top_p', 'seed') if k in kwargs}
    request_ref = capture('provider-request', payload)
    settings = {k: kwargs[k] for k in ('model', 'max_tokens', 'stream', 'reasoning_effort',
                'extra_body', 'response_format', 'temperature', 'top_p', 'seed') if k in kwargs}
    event = cancel_event.get()
    started = time.perf_counter()
    try:
        for attempt in range(5):
            if event is not None and event.is_set():
                raise RequestCancelled('Run cancelled.')
            metrics[phase + '_llm_calls'] = metrics.get(phase + '_llm_calls', 0) + 1
            request = dict(phase=phase, attempt=attempt+1, settings=settings,
                           operation=operation.get(), usage_complete=False,
                           context_artifact=metrics.get('context_artifact'),
                           memory_state_artifact=metrics.get('memory_state_artifact'),
                           request_sha256=sha256(payload), request_artifact=request_ref,
                           provider='deepseek', endpoint='https://api.deepseek.com/chat/completions',
                           provider_default_parameters=[k for k in ('temperature', 'top_p', 'seed', 'max_tokens',
                               'reasoning_effort', 'response_format') if k not in kwargs],
                           returned_model=None, system_fingerprint=None, tokens=None,
                           immutable_provider_version_available=False, status='started')
            if provenance is not None:
                provenance.setdefault('provider_requests', []).append(request)
            callback = checkpoint.get()
            if callback:
                callback()
            attempt_started = time.perf_counter()
            try:
                response = api_client.with_options(max_retries=0, timeout=180).chat.completions.create(**kwargs)
                request['provider_seconds'] = time.perf_counter() - attempt_started
                usage = getattr(response, 'usage', None)
                request.update(status='completed', returned_model=getattr(response, 'model', None),
                    system_fingerprint=getattr(response, 'system_fingerprint', None),
                    response_id=getattr(response, 'id', None), tokens=getattr(usage, 'total_tokens', None),
                    prompt_tokens=getattr(usage, 'prompt_tokens', None),
                    completion_tokens=getattr(usage, 'completion_tokens', None))
                if usage is not None and hasattr(usage, 'model_dump'):
                    request['usage_details'] = usage.model_dump(mode='json')
                request['usage_complete'] = request['tokens'] is not None
                request['response_artifact'] = capture('provider-response', dict(
                    response_id=getattr(response, 'id', None), model=getattr(response, 'model', None),
                    choices=[dict(content=getattr(c.message, 'content', None),
                                  finish_reason=getattr(c, 'finish_reason', None)) for c in response.choices]))
                if callback:
                    callback()
                return response
            except Exception as error:
                request['provider_seconds'] = time.perf_counter() - attempt_started
                request.update(status='error', status_code=status_code(error),
                    exception_type=type(error).__name__, error=str(error),
                    cause_type=type(error.__cause__).__name__ if error.__cause__ else None,
                    cause=str(error.__cause__) if error.__cause__ else None)
                from openai import APIConnectionError, APITimeoutError
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
                request['seconds'] = time.perf_counter() - attempt_started
                if callback:
                    callback()
    finally:
        metrics[phase + '_seconds'] = time.perf_counter() - started
        metrics[phase + '_timing_scope'] = 'wall time including retries, backoff and audit checkpoints; provider_seconds measures the SDK transport call'
