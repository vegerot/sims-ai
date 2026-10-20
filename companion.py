"""Generate banter outside the game's legacy Python and game thread.

Uses the existing OPENROUTER_API_KEY environment variable. No dependencies.
"""

import argparse
import json
import os
import sys
from pathlib import Path
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent


def generate(event, model):
    api_key = os.environ['OPENROUTER_API_KEY']
    # Only the observed scene goes upstream, not the rest of the save or its log.
    scene = {'interaction': event['interaction']}
    for role in ('actor', 'target'):
        scene[role] = {key: value for key, value in event[role].items() if key != 'id'}
    if 'relationship' in event:
        scene['relationship'] = event['relationship']
    request = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps({
            'model': model,
            'messages': [
                {'role': 'system', 'content': (ROOT / 'prompt.txt').read_text(encoding='utf-8')},
                {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
            ],
            'max_tokens': 300,
        }).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
        method='POST',
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    text = result['choices'][0]['message']['content'].strip()
    if not text:
        raise ValueError('The model returned no dialogue.')
    if len(text) > 1000:
        raise ValueError('The model exceeded the short-dialogue limit.')
    return {
        'event_id': event['event_id'],
        'text': text,
        'model': result.get('model', model),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'usage': result.get('usage', {}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path)
    parser.add_argument('--reply-file', type=Path,
                        help='Output in the experiment workspace, outside protected Documents.')
    parser.add_argument('--once', type=Path, help='Generate once from a captured event JSON file.')
    parser.add_argument('--model', default='openai/gpt-6-luna')
    args = parser.parse_args()
    if not os.environ.get('OPENROUTER_API_KEY'):
        parser.error('OPENROUTER_API_KEY is not set.')
    if args.once:
        print(json.dumps(generate(json.loads(args.once.read_text(encoding='utf-8-sig')), args.model),
                         ensure_ascii=False, indent=2), flush=True)
        return
    if args.data_directory is None or args.reply_file is None:
        parser.error('--data-directory and --reply-file are required unless --once is used.')

    data = args.data_directory
    args.reply_file.parent.mkdir(parents=True, exist_ok=True)
    events = data / 'events.jsonl'
    # Starting at the end avoids generating old scenes after a companion restart.
    with events.open('r', encoding='utf-8') as incoming:
        incoming.seek(0, os.SEEK_END)
        print('Listening for new AI-mode socials in {}'.format(data), flush=True)
        while True:
            offset = incoming.tell()
            line = incoming.readline()
            if not line or not line.endswith('\n'):
                incoming.seek(offset)
                time.sleep(0.25)
                continue
            event = json.loads(line)
            if event.get('type') != 'social' or event.get('mode') != 'ai':
                continue
            if time.time() - event['observed_at'] > 25:
                continue
            try:
                reply = generate(event, args.model)
                print('{}s: {}'.format(reply['elapsed_seconds'], reply['text']), flush=True)
            except urllib.error.HTTPError as error:
                reply = {'event_id': event['event_id'], 'error': 'HTTP {}'.format(error.code)}
                print(reply['error'], flush=True)
            except Exception as error:
                # Exception type gives diagnostics without printing credentials or response bodies.
                reply = {'event_id': event['event_id'], 'error': type(error).__name__}
                print(reply['error'], flush=True)
            temporary = args.reply_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, args.reply_file)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except KeyboardInterrupt:
        pass
