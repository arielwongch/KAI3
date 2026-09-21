# Please install OpenAI SDK first: `pip3 install openai`
import os
import time
from dataclasses import dataclass, field
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timezone, timedelta

# ==============================================
# ENV CONFIG
# ==============================================

load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

# ==============================================
# DEFINITIONS
# ==============================================

@dataclass
class PerformanceMetric:
    token_usage: int = 0
    latency: float = 0.0

# ==============================================
# FUNCTIONS
# ==============================================

def print_header(): 
    print() 
    print("╭──────────────────────────────────────────────────────────╮") 
    print("│                                                          │") 
    print("│                      DEEPSEEK CHAT                       │") 
    print("│                  Terminal AI Assistant                   │")
    print("│                                                          │") 
    print("╰──────────────────────────────────────────────────────────╯") 
    print(" Press Ctrl+C to exit the chat or type 'exit', 'quit', or 'q' to quit.") 
    print(" Type 'metrics' to view performance metrics.")
    print("────────────────────────────────────────────────────────────") 
    print()

def print_next_line():
    print()
    print("────────────────────────────────────────────────────────────")
    print()

def print_performance_metrics(metrics: list[PerformanceMetric]):

    if not metrics:
        print("No performance metrics to display.")
        return

    total_tokens = sum(metric.token_usage for metric in metrics)
    total_latency = sum(metric.latency for metric in metrics)
    avg_latency = total_latency / len(metrics)

    print("Performance Metrics:")
    print(f"  Total Token Usage: {total_tokens}")
    print(f"  Average Latency: {avg_latency:.4f} seconds")
    print(f"  Total Latency: {total_latency:.4f} seconds")
    print(f"  Number of Requests: {len(metrics)}")

def print_performance_metrics_summary(metrics: list[PerformanceMetric]):
    if not metrics:
        print("No performance metrics to display.")
        return

    total_tokens = sum(metric.token_usage for metric in metrics)
    total_latency = sum(metric.latency for metric in metrics)
    avg_latency = total_latency / len(metrics)

    print("===============================================")
    print("Performance Metrics Summary:")
    print(f"  Total Token Usage: {total_tokens}")
    print(f"  Average Latency: {avg_latency:.4f} seconds")
    print(f"  Total Latency: {total_latency:.4f} seconds")
    print(f"  Number of Requests: {len(metrics)}")
    print("===============================================")

# ==============================================
# CONVO
# ==============================================

print_header()

init_message = [
    {"role": "system", "content": "You are a helpful assistant"},
]

memory = []

# Create a timezone object for UTC+8
utc_8 = timezone(timedelta(hours=8))

PerformanceMetrics: List[PerformanceMetric] = []

while True:
    try:
        user_input = input("You\n> ")
        if user_input.lower() in ["exit", "quit", "q"]:
            print("Exiting...")
            break
        if user_input.strip() == "":
            print("Please enter a message.")
            continue
        if user_input.lower() == "metrics":
            print_performance_metrics(PerformanceMetrics)
            print_next_line()
            continue
    except KeyboardInterrupt:
        print()
        print("Exiting...")
        break
    
    user_input_time = datetime.now(utc_8)
    print(f"{user_input_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)")
    print()

    # sliding window implementation
    memory.append({"role": "user", "content": user_input})

    messages = init_message + memory

    start_time = time.perf_counter()

    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    latency = time.perf_counter() - start_time
    response_time = datetime.now(utc_8)
    usage = response.usage
    total_tokens = usage.total_tokens

    PerformanceMetrics.append(PerformanceMetric(
        token_usage=total_tokens,
        latency=latency
    ))

    memory.append(response.choices[0].message)
    print(f"AI Assistant\n> {response.choices[0].message.content}")
    print(f"{response_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)")
    print_next_line()

print_performance_metrics_summary(PerformanceMetrics)
