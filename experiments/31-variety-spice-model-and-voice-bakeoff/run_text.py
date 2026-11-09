"""Text bake-off: every model x prompt over the frozen scene set, timed exactly like companion.generate().

python3.15 run_text.py [--models a,b] [--prompts v1,v2] [--samples 1]  ->  appends to text-results.jsonl
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMS = HERE.parents[1]
sys.path.insert(0, str(SIMS))
import companion as c  # noqa: E402

MODELS = [
    'openai/gpt-6-luna', 'openai/gpt-6.1-terra', 'x-ai/grok-4.20', 'x-ai/grok-4.3',
    'deepseek/deepseek-v4.1-flash-1017', 'z-ai/glm-5.2', 'minimax/minimax-m3.1-flash',
    'mistralai/mistral-small-2603', 'google/gemini-omni-1.2-flash',
]
PROMPTS = {'v1': HERE / 'prompt-v1.txt', 'v2': HERE / 'prompt-v2.txt', 'v3': HERE / 'prompt-v3.txt'}
OUT = HERE / 'text-results.jsonl'
_lock = threading.Lock()


def scene_for(event: dict, prompt: str, mem: c.MemoryStore) -> dict:
    actor = str(event['actor'].get('name') or '')
    tname = mem.event_target_name(event)
    scene = c.build_scene(
        event, language=event['_language'], pair_memory=mem.get_memory(actor, tname),
        recent_gossip=mem.get_gossip(actor, tname),
        recent_lines=mem.get_recent_lines(actor, tname) if prompt != 'v1' else None,
    )
    if prompt == 'v1':  # Exactly what production sent before this experiment.
        scene.pop('spicy', None)
    return scene


def run_one(model: str, prompt: str, name: str, event: dict, scene: dict, sample: int) -> None:
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': PROMPTS[prompt].read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
        ],
        'max_tokens': 320,
        'reasoning': {'effort': 'none'},
    }
    row = {'model': model, 'prompt': prompt, 'scene': name, 'sample': sample,
           'spicy': bool(c.is_spicy(event)), 'language': scene['language'], 'event_type': scene['event_type']}
    started = time.monotonic()
    try:
        resp = c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=40)
        result = json.loads(resp.read().decode('utf-8'))
        row['elapsed_s'] = round(time.monotonic() - started, 3)
        msg = result['choices'][0]['message']
        row['raw_text'] = (msg.get('content') or '').strip()
        row['text'] = c._normalize_dialogue_lines(row['raw_text'], event, speaker_count=scene['speaker_count']) if row['raw_text'] else ''
        row['finish_reason'] = result['choices'][0].get('finish_reason')
        row['provider'] = result.get('provider')
        usage = result.get('usage') or {}
        row['cost_usd'] = usage.get('cost')
        row['reasoning_tokens'] = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
    except Exception as exc:  # Record and keep going: one model's 400 shouldn't stop the grid.
        row['elapsed_s'] = round(time.monotonic() - started, 3)
        body = getattr(exc, 'body', None) or (exc.read().decode('utf-8', 'replace') if hasattr(exc, 'read') else '')
        row['error'] = f'{type(exc).__name__}: {exc} {body[:300]}'
    with _lock, OUT.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f"{model:36s} {prompt} {name:34s} {row['elapsed_s']:6.2f}s {(row.get('text') or row.get('error') or '')[:90]!r}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default=','.join(MODELS))
    ap.add_argument('--prompts', default='v1,v2')
    ap.add_argument('--samples', type=int, default=1)
    ap.add_argument('--scenes', default='', help='comma-separated scene-name prefixes')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()
    c.load_stbl_dictionary()
    mem = c.MemoryStore(HERE / 'scenes' / '_mem')  # Loads scenes/_mem/memories.json (a frozen snapshot).
    scenes = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted((HERE / 'scenes').glob('[0-9]*.json'))}
    if args.scenes:
        scenes = {k: v for k, v in scenes.items() if k.startswith(tuple(args.scenes.split(',')))}
    jobs = []
    for model in args.models.split(','):
        for prompt in args.prompts.split(','):
            for name, ev in scenes.items():
                sc = scene_for(ev, prompt, mem)
                for s in range(args.samples):
                    jobs.append((model, prompt, name, ev, sc, s))
    print(len(jobs), 'calls', flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for j in jobs:
            pool.submit(run_one, *j)


if __name__ == '__main__':
    main()
