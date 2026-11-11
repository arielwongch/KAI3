"""Interactive chat using the shared lazy provider and bounded request policy."""
import argparse
import json
import time
from ProviderClient import client
from RequestPolicy import completion


def print_performance_metrics(metrics):
    if not metrics:
        print('No performance metrics to display.')
        return
    known = [m['agent_tokens'] for m in metrics if m.get('agent_tokens') is not None]
    print(f'Requests: {len(metrics)}; known answer tokens: {sum(known)}; '
          f'usage incomplete: {len(known) != len(metrics)}; '
          f'processing seconds: {sum(m.get("total_seconds", 0) for m in metrics):.3f}')


def raw_turn(user_input, memory, diagnostics):
    """Commit a complete pair only after a valid response; retain failed usage."""
    started = time.perf_counter()
    try:
        messages = [{'role': 'system', 'content': 'You are a helpful assistant'},
                    *memory, {'role': 'user', 'content': user_input}]
        response = completion(client, diagnostics, phase='agent', model='deepseek-flash',
            messages=messages, stream=False, reasoning_effort='high',
            extra_body={'thinking': {'type': 'enabled'}})
        diagnostics['agent_tokens'] = getattr(getattr(response, 'usage', None), 'total_tokens', None)
        choice = response.choices[0]
        answer = (choice.message.content or '').strip()
        if not answer or getattr(choice, 'finish_reason', None) not in (None, 'stop'):
            raise ValueError('The provider returned an empty or incomplete answer.')
        memory.extend([{'role': 'user', 'content': user_input},
                       {'role': 'assistant', 'content': answer}])
        diagnostics['status'] = 'completed'
        return answer
    except Exception as error:
        diagnostics.update(status='error', error=str(error))
        raise
    finally:
        from ResultAnalysis import phase_tokens
        diagnostics['agent_tokens'] = phase_tokens(diagnostics, 'agent')
        diagnostics['total_seconds'] = time.perf_counter() - started


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory-module', choices=['raw', 'compaction'], default='raw')
    parser.add_argument('--retain-percent', type=float, default=50)
    parser.add_argument('--compaction-mode', choices=['one_shot', 'repeated'], default='repeated',
                        help='one_shot uses manual /compact commands in terminal chat.')
    parser.add_argument('--compaction-trigger-tokens', type=int, default=2000)
    parser.add_argument('--memory-context-tokens', type=int, default=8000)
    args = parser.parse_args(argv)
    module = None
    if args.memory_module == 'compaction':
        from Compaction import Compaction
        module = Compaction(retain_percent=args.retain_percent, compaction_mode=args.compaction_mode,
            compaction_trigger_tokens=args.compaction_trigger_tokens,
            memory_context_tokens=args.memory_context_tokens)
    print('KAI3 terminal chat. Type exit to quit or metrics for usage.')
    if module is not None:
        print('Use /compact [retained percent] for compaction; /retry-memory retries a failed write.')
    memory, metrics, pending = [], [], None
    try:
        while True:
            try:
                text = input('You\n> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in ('exit', 'quit', 'q'):
                print('Exiting...')
                break
            if not text:
                continue
            if text.lower() == 'metrics':
                print_performance_metrics(metrics)
                if module is not None:
                    print(json.dumps(dict(memory=module.inspect(), operations=metrics), ensure_ascii=False, indent=2))
                continue
            if pending is not None and text != '/retry-memory':
                print('Use /retry-memory before continuing.')
                continue
            d = dict(agent_tokens=0, agent_llm_calls=0, memory_tokens=0, memory_llm_calls=0,
                     write_seconds=0., total_seconds=0.)
            started = time.perf_counter()
            try:
                if pending is not None:
                    from ReAct import _write
                    from Diagnostics import collector
                    from MemoryEntry import MemoryEntry
                    token = collector.set(d)
                    try:
                        _write(module, d, MemoryEntry(**pending))
                    finally:
                        collector.reset(token)
                    pending = d.get('pending_write')
                    print(d.get('warning') or 'Memory updated.')
                elif module is not None and (text == '/compact' or text.startswith('/compact ')):
                    from Diagnostics import collector
                    percent = float(text.split(maxsplit=1)[1]) if ' ' in text else None
                    token = collector.set(d)
                    try:
                        event = module.compact(percent)
                    finally:
                        collector.reset(token)
                    print(f'Memory: {event["before_tokens"]} -> {event["after_tokens"]} tokens')
                elif module is not None:
                    from ReAct import run_ReAct
                    answer, _, _ = run_ReAct(text, memory_module=module, diagnostics=d)
                    print(answer)
                    pending = d.get('pending_write')
                    if d.get('warning'):
                        print(d['warning'])
                else:
                    print(raw_turn(text, memory, d))
            except Exception as error:
                print(f'Request failed: {error}')
            finally:
                d['total_seconds'] = time.perf_counter() - started
                metrics.append(d)
    except KeyboardInterrupt:
        print('\nExiting.')
    finally:
        print_performance_metrics(metrics)


if __name__ == '__main__':
    main()
