# Please install OpenAI SDK first: `pip3 install openai`
import os
import time
import re
from dotenv import load_dotenv
from openai import OpenAI

# ==============================================
# ENV CONFIG
# ==============================================

load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

# ==============================================
# ReAct FUNCTION
# ==============================================

def run_ReAct(system_prompt:str,user_input:str):

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    start_time = time.perf_counter()

    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    response_text = response.choices[0].message.content
    latency = time.perf_counter() - start_time
    total_tokens = response.usage.total_tokens
    
    return response_text, latency, total_tokens
        