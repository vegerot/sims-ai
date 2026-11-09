"""Session simulation: replay all scenes 3x in order with memory recording, like a real evening of play.

Repetition only shows up across a session (pair_memory + recent_lines_elsewhere), so single calls can't measure it.
python3.15 run_session.py model:prompt [model:prompt ...]  ->  session-results.jsonl
"""
import copy
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import run_text as rt

c = rt.c
OUT = rt.HERE / 'session-results.jsonl'
_lock = threading.Lock()


def run_session(spec: str, passes: int = 3) -> None:
    model, prompt = spec.split(':')
    snap = json.loads((rt.HERE / 'scenes' / '_mem' / 'memories.json').read_text(encoding='utf-8'))
    mem = c.MemoryStore()  # path=None: record() keeps memory in RAM only.
    mem.pairs = copy.deepcopy(snap['pairs'])
    scenes = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted((rt.HERE / 'scenes').glob('[0-9]*.json'))}
    for i in range(passes):
        for name, ev in scenes.items():
            sc = rt.scene_for(ev, prompt, mem)
            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': rt.PROMPTS[prompt].read_text(encoding='utf-8')},
                    {'role': 'user', 'content': json.dumps(sc, ensure_ascii=False)},
                ],
                'max_tokens': 320, 'reasoning': {'effort': 'none'},
            }
            t0 = time.monotonic()
            row = {'model': model, 'prompt': prompt, 'pass': i, 'scene': name, 'spicy': c.is_spicy(ev)}
            try:
                res = json.loads(c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=40).read())
                raw = (res['choices'][0]['message'].get('content') or '').strip()
                row['text'] = c._normalize_dialogue_lines(raw, ev, speaker_count=sc['speaker_count']) if raw else ''
                if row['text']:
                    mem.record(ev, sc, row['text'])
            except Exception as exc:
                row['error'] = str(exc)[:200]
            row['elapsed_s'] = round(time.monotonic() - t0, 3)
            with _lock, OUT.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('done', spec, flush=True)


if __name__ == '__main__':
    c.load_stbl_dictionary()
    with ThreadPoolExecutor(len(sys.argv) - 1) as pool:
        list(pool.map(run_session, sys.argv[1:]))
