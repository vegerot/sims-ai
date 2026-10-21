"""Compare provider-default reasoning with none using the same public test scene.

Run with python3.15. Makes six model calls; never reads original saves.
"""

import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from companion import generate


def main() -> None:
    fixture = ROOT / 'experiments/02-context-and-generation/result.json'
    event = json.loads(fixture.read_text(encoding='utf-8'))['generation_requests'][-1]
    calls = []
    # Alternate the order within each pair to reduce a systematic warm-up advantage.
    for effort in (None, 'none', 'none', None, None, 'none'):
        reply = generate(event, 'openai/gpt-6-luna', effort)
        calls.append(reply)
        reasoning = reply['usage'].get('completion_tokens_details', {}).get('reasoning_tokens')
        print(json.dumps({'effort': effort, 'seconds': reply['elapsed_seconds'],
                          'reasoning_tokens': reasoning, 'text': reply['text']},
                         ensure_ascii=False), flush=True)
    result = {
        'experiment': 'Python 3.15: provider-default reasoning versus explicit none',
        'python': sys.version,
        'scene': event,
        'prompt_sha256': hashlib.sha256((ROOT / 'prompt.txt').read_bytes()).hexdigest(),
        'calls': calls,
        'median_seconds': {
            label: statistics.median(r['elapsed_seconds'] for r in calls
                                     if r['reasoning_effort'] == effort)
            for label, effort in [('provider_default', None), ('none', 'none')]
        },
        'limits': [
            'Three requests per condition; descriptive comparison, not a latency SLA.',
            'Same scene and prompt; outputs vary and provider routing/cache state is uncontrolled.',
            'Elapsed time covers the model request and response, not game polling or speech.',
            'Dialogue quality has not been systematically evaluated.',
        ],
    }
    output = Path(__file__).with_name('result.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['median_seconds']), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
