# Please install OpenAI SDK first: `pip3 install openai`
import os
import time
import re
from dotenv import load_dotenv
from openai import OpenAI
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule
from Diagnostics import collector, entries_json

# ==============================================
# ENV CONFIG
# ==============================================

load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

ACTION_RESPONSE = re.compile(
    r"\AThought:\s*.+\nAction:\s*([^:\n]+):\s*(.+)\Z",
    re.DOTALL,
)
FINAL_RESPONSE = re.compile(
    r"\AThought:\s*I have the final answer\.\s*\nFinal Answer:\s*(.+)\Z",
    re.DOTALL,
)

# ==============================================
# ReAct FUNCTION
# ==============================================

def _run_ReAct(
    user_input: str,
    max_iterations: int = 10,
    memory_module: MemoryModule | None = None,
    diagnostics=None, write_back=True,
):
    if memory_module is None:
        raise ValueError("Please provide a valid memory_module instance.")

    if memory_module is not None and not isinstance(memory_module, MemoryModule):
        raise TypeError("memory_module must be of type - MemoryModule")

    if memory_module is not None:
        retrieval_start = time.perf_counter()
        try:
            memory_entries = memory_module.retrieve(query=user_input, k=5)
        finally:
            diagnostics["retrieval_seconds"] = time.perf_counter() - retrieval_start
        diagnostics["retrieved"] = entries_json(memory_entries)
        diagnostics["retrieved_count"] = len(memory_entries)
        memory_text = "\n".join(entry.text for entry in memory_entries)
    else:
        memory_text = ""

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
    response_text = ""

    result.append("Starting Agent Task:")
    for i in range(max_iterations):

        result.append(f"Iteration {i+1}:")

        call_start = time.perf_counter()
        diagnostics["agent_llm_calls"] += 1
        try:
            response = client.chat.completions.create(
                model="deepseek-flash", messages=messages, stream=False,
                reasoning_effort="high", extra_body={"thinking": {"type": "enabled"}},
            )
        except Exception:
            diagnostics["agent_tokens"] = None
            raise
        finally:
            latency += time.perf_counter() - call_start
            diagnostics["agent_seconds"] = latency
        tokens = getattr(getattr(response, "usage", None), "total_tokens", None)
        if tokens is None:
            diagnostics["agent_tokens"] = None
        else:
            total_tokens += tokens
            if diagnostics["agent_tokens"] is not None:
                diagnostics["agent_tokens"] = total_tokens

        messages.append(response.choices[0].message)
        response_text = response.choices[0].message.content
        response_text = response_text.strip()
        
        result.append(f"Response: {response_text}")

        if FINAL_RESPONSE.fullmatch(response_text):
            result.append("Task completed successfully.")
            diagnostics["status"] = "completed"
            diagnostics["final_answer"] = FINAL_RESPONSE.fullmatch(response_text).group(1)
            if write_back:
                _write(memory_module, diagnostics, MemoryEntry(
                    text=f"User: {user_input}\nAssistant: {response_text}",
                    metadata={"type": "conversation", "user_text": user_input,
                              "assistant_text": FINAL_RESPONSE.fullmatch(response_text).group(1)},
                ))
            return "\n\n".join(result), latency, total_tokens

        observation = ACTION_RESPONSE.fullmatch(response_text)

        if observation:
            messages.append({"role": "user", "content": f"Observation: {observation.group(2)}"})
        else:
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response did not match the required format. "
                    "Reply with exactly one of these formats and no extra text:\n"
                    "Thought: [brief reasoning]\n"
                    "Action: [action]: [argument]\n\n"
                    "Thought: I have the final answer.\n"
                    "Final Answer: [your response]"
                ),
            })

    result.append("Max iterations reached without finding a final answer.")

    diagnostics["status"] = "incomplete"
    if write_back:
        _write(memory_module, diagnostics, MemoryEntry(
            text=f"User: {user_input}\nAssistant: {response_text}",
            metadata={"type": "conversation", "completed": False,
                      "user_text": user_input, "assistant_text": response_text},
        ))

    return "\n".join(result), latency, total_tokens



def _write(module, diagnostics, entry):
    started = time.perf_counter()
    try:
        module.write(entry)
    finally:
        diagnostics["write_seconds"] += time.perf_counter() - started


def run_ReAct(user_input, max_iterations=10, memory_module=None, diagnostics=None, write_back=True):
    """Keep the legacy return tuple while optionally collecting detached diagnostics."""
    d = diagnostics if diagnostics is not None else {}
    d.update(status="running", query=user_input, final_answer=None, retrieved=[],
             retrieved_count=0, retrieval_seconds=0.0, agent_seconds=0.0, write_seconds=0.0,
             agent_tokens=0, memory_tokens=0, agent_llm_calls=0, memory_llm_calls=0)
    started = time.perf_counter()
    token = collector.set(d)
    valid = isinstance(memory_module, MemoryModule)
    try:
        if valid:
            d["stored_before"] = len(memory_module.inspect()["entries"])
        return _run_ReAct(user_input, max_iterations, memory_module, d, write_back)
    except Exception as error:
        d.update(status="error", error=str(error))
        raise
    finally:
        try:
            if valid:
                d["stored_after"] = len(memory_module.inspect()["entries"])
        finally:
            d["total_seconds"] = time.perf_counter() - started
            collector.reset(token)
