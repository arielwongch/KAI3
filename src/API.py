import time
from RequestPolicy import completion
from Diagnostics import collector, memory_request_options, memory_response
from ProviderClient import client


def call_api(system_prompt: str, user_input: str):

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    start_time = time.perf_counter()

    response = completion(client, phase='memory',
        model="deepseek-flash",
        messages=messages,
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
        **memory_request_options.get()
    )

    response_text = response.choices[0].message.content
    latency = time.perf_counter() - start_time
    usage = getattr(response, 'usage', None)
    total_tokens = getattr(usage, 'total_tokens', None)
    memory_response.set(dict(response_id=getattr(response, 'id', None),
        system_prompt=system_prompt,
        finish_reason=getattr(response.choices[0], 'finish_reason', None),
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None)))
    if usage is not None and hasattr(usage, 'model_dump'):
        memory_response.get()['usage_details'] = usage.model_dump(mode='json')
    metrics = collector.get()
    if metrics is not None:
        for field, usage_field in (('memory_prompt_tokens', 'prompt_tokens'), ('memory_completion_tokens', 'completion_tokens')):
            value = getattr(usage, usage_field, None)
            metrics[field] = None if value is None or metrics.get(field, 0) is None else metrics.get(field, 0) + value
    
    return response_text, latency, total_tokens
