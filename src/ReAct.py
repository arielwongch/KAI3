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

def run_ReAct(user_input:str, memory:list[str]=[""],max_iterations:int=10):

    memory_text = "\n".join(memory) if memory else ""

    system_prompt = f"""
    You are a helpful assistant. You must solve the user's request by looping through three stages: Thought, Action, and Observation.

    Use the following user memories to guide your response:
    {memory_text}

    Your output format MUST strictly look like this:
    Thought: [Reason about what to do next]
    Action: [action]: [argument]

    When you have the final answer, output:
    Thought: I have the final answer.
    Final Answer: [Your final response to the user]
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    result = []
    latency = 0.0
    total_tokens = 0

    result.append("Starting Agent Task:")
    start_time = time.perf_counter()

    for i in range(max_iterations):

        result.append(f"Iteration {i+1}:")

        response = client.chat.completions.create(
            model="deepseek-flash",
            messages=messages,
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}}
        )

        latency += time.perf_counter() - start_time
        total_tokens += response.usage.total_tokens

        messages.append(response.choices[0].message)
        response_text = response.choices[0].message.content
        
        result.append(f"Response: {response_text}")

        if "Final Answer:" in response_text:
            result.append("Task completed successfully.")
            return "\n".join(result), latency, total_tokens

        observation = re.search(r"Action:\s*(.*)", response_text)

        if observation:
            messages.append({"role": "user", "content": f"Observation: {observation.group(1)}"})

    result.append("Max iterations reached without finding a final answer.")
    
    return "\n".join(result), latency, total_tokens
        