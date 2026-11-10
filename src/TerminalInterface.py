import os
import time
import argparse
import json
from dataclasses import dataclass
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timezone, timedelta

load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

@dataclass
class PerformanceMetric:
    token_usage: int = 0
    latency: float = 0.0

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

parser = argparse.ArgumentParser(description='Interactive chat, optionally with measured compaction memory.')
parser.add_argument('--memory-module', choices=['raw', 'compaction'], default='raw')
parser.add_argument('--retain-percent', type=float, default=50)
parser.add_argument('--compaction-mode', choices=['one_shot', 'repeated'], default='repeated',
                    help='one_shot uses manual /compact commands in terminal chat.')
parser.add_argument('--compaction-trigger-tokens', type=int, default=2000)
parser.add_argument('--memory-context-tokens', type=int, default=8000)
args = parser.parse_args()
compaction_memory = None
if args.memory_module == 'compaction':
    from Compaction import Compaction
    from ReAct import run_ReAct
    from Diagnostics import collector
    compaction_memory = Compaction(retain_percent=args.retain_percent, compaction_mode=args.compaction_mode,
        compaction_trigger_tokens=args.compaction_trigger_tokens, memory_context_tokens=args.memory_context_tokens)

print_header()
if compaction_memory is not None:
    print('Compaction enabled. Use /compact [retained percent] to compact the current memory.')

init_message = [
    {"role": "system", "content": "You are a helpful assistant"},
]

memory = []

utc_8 = timezone(timedelta(hours=8))

PerformanceMetrics: list[PerformanceMetric] = []
compaction_metrics = []

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
            if compaction_memory is not None:
                print(json.dumps(dict(memory=compaction_memory.inspect(), operations=compaction_metrics),
                                 ensure_ascii=False, indent=2))
                continue
            print_performance_metrics(PerformanceMetrics)
            print_next_line()
            continue
    except KeyboardInterrupt:
        print()
        print("Exiting...")
        break
    
    user_input_time = datetime.now(utc_8)
    if compaction_memory is not None:
        if user_input == '/compact' or user_input.startswith('/compact '):
            try:
                percent = float(user_input.split(maxsplit=1)[1]) if ' ' in user_input else None
                metrics = dict(memory_llm_calls=0, memory_tokens=0)
                token = collector.set(metrics)
                try:
                    event = compaction_memory.compact(percent)
                finally:
                    compaction_metrics.append(dict(operation='manual_compaction', **metrics))
                    collector.reset(token)
                print(f"Memory: {event['before_tokens']} -> {event['after_tokens']} tokens; actual retained {event.get('actual_retain_percent')}%")
                print(f"Compaction provider tokens: {metrics['memory_tokens']}; attempts: {metrics['memory_llm_calls']}")
            except (ValueError, RuntimeError) as error:
                print(str(error))
        else:
            diagnostics = {}
            try:
                result, latency, tokens = run_ReAct(user_input, memory_module=compaction_memory, diagnostics=diagnostics)
                print(result)
                print(f"Answer tokens: {diagnostics['agent_tokens']}; compaction tokens: {diagnostics['memory_tokens']}; seconds: {diagnostics['total_seconds']:.3f}")
            except Exception as error:
                print(str(error))
            finally:
                compaction_metrics.append(diagnostics)
        continue
    print(f"{user_input_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)")
    print()

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
