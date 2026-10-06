# Please install OpenAI SDK first: `pip3 install openai`
import os
import time
from pathlib import Path
from RequestPolicy import completion
from Diagnostics import collector
from dotenv import load_dotenv
from openai import OpenAI

# ==============================================
# ENV CONFIG
# ==============================================

load_dotenv(Path(__file__).with_name('.env'))

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

# ==============================================
# Call API FUNCTION
# ==============================================

def call_api(system_prompt:str,user_input:str):

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
        extra_body={"thinking": {"type": "enabled"}}
    )

    response_text = response.choices[0].message.content
    latency = time.perf_counter() - start_time
    usage = getattr(response, 'usage', None)
    total_tokens = getattr(usage, 'total_tokens', None)
    metrics = collector.get()
    if metrics is not None:
        for field, usage_field in (('memory_prompt_tokens', 'prompt_tokens'), ('memory_completion_tokens', 'completion_tokens')):
            value = getattr(usage, usage_field, None)
            metrics[field] = None if value is None or metrics.get(field, 0) is None else metrics.get(field, 0) + value
    
    return response_text, latency, total_tokens
