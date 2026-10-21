"""Generate banter outside the game's legacy Python and game thread.

Uses the existing OPENROUTER_API_KEY environment variable. Pure Python 3.15 stdlib.
"""

import argparse
import html
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib


ROOT = Path(__file__).resolve().parent
DEFAULT_GAME_DIR = Path(r'C:\Program Files\EA Games\The Sims 4')
DEFAULT_MODS_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods')
STBL_CACHE_PATH = ROOT / '.local' / 'stbl_en_us.json'
_stbl_cache: dict[int, str] | None = None
_tts_worker: subprocess.Popen | None = None


def _refpack_decompress(data: bytes) -> bytes:
    offset = 4 if (len(data) >= 6 and data[4] in (0x10, 0x50) and data[5] == 0xFB) else 0
    flags = data[offset]
    offset += 2
    if flags & 0x80:
        decompressed_size = struct.unpack_from('>I', data, offset)[0]
        offset += 4
    else:
        decompressed_size = (data[offset] << 16) | (data[offset + 1] << 8) | data[offset + 2]
        offset += 3
    output = bytearray()
    src = offset
    n = len(data)
    while src < n:
        code = data[src]
        if code <= 0x7F:
            if src + 1 >= n:
                break
            b1 = data[src + 1]
            num_lit = code & 0x03
            copy_len = ((code & 0x1C) >> 2) + 3
            copy_off = ((code & 0x60) << 3) + b1 + 1
            src += 2
            output.extend(data[src:src + num_lit])
            src += num_lit
            csrc = len(output) - copy_off
            for i in range(copy_len):
                output.append(output[csrc + i])
        elif code <= 0xBF:
            if src + 2 >= n:
                break
            b1, b2 = data[src + 1], data[src + 2]
            num_lit = ((b1 & 0xC0) >> 6) & 0x03
            copy_len = (code & 0x3F) + 4
            copy_off = ((b1 & 0x3F) << 8) + b2 + 1
            src += 3
            output.extend(data[src:src + num_lit])
            src += num_lit
            csrc = len(output) - copy_off
            for i in range(copy_len):
                output.append(output[csrc + i])
        elif code <= 0xDF:
            if src + 3 >= n:
                break
            b1, b2, b3 = data[src + 1], data[src + 2], data[src + 3]
            num_lit = code & 0x03
            copy_len = ((code & 0x0C) << 6) + b3 + 5
            copy_off = ((code & 0x10) << 12) + (b1 << 8) + b2 + 1
            src += 4
            output.extend(data[src:src + num_lit])
            src += num_lit
            csrc = len(output) - copy_off
            for i in range(copy_len):
                output.append(output[csrc + i])
        elif code <= 0xFB:
            num_lit = ((code & 0x1F) << 2) + 4
            src += 1
            output.extend(data[src:src + num_lit])
            src += num_lit
        else:
            num_lit = code & 0x03
            src += 1
            output.extend(data[src:src + num_lit])
            break
    return bytes(output[:decompressed_size])


def _read_package_stbls(pkg_path: Path) -> dict[int, str]:
    data = pkg_path.read_bytes()
    if data[:4] != b'DBPF':
        return {}
    index_count = struct.unpack_from('<I', data, 36)[0]
    index_offset = struct.unpack_from('<I', data, 64)[0] or struct.unpack_from('<I', data, 40)[0]
    pos = index_offset
    flags = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    const_type = None
    if flags & 1:
        const_type = struct.unpack_from('<I', data, pos)[0]
        pos += 4
    if flags & 2:
        pos += 4
    if flags & 4:
        pos += 4
    if flags & 8:
        pos += 4
    out: dict[int, str] = {}
    for _ in range(index_count):
        rtype = const_type if (flags & 1) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 1):
            pos += 4
        if not (flags & 2):
            pos += 4
        if not (flags & 4):
            pos += 4
        if not (flags & 8):
            pos += 4
        offset, size_raw, mem_size, comp_type = struct.unpack_from('<IIIH', data, pos)
        pos += 16
        size = size_raw & 0x7FFFFFFF
        if rtype != 0x220557DA:
            continue
        chunk = data[offset:offset + size]
        if comp_type and size != mem_size:
            if (len(chunk) >= 2 and chunk[0] in (0x10, 0x50) and chunk[1] == 0xFB) or (
                len(chunk) >= 6 and chunk[4] in (0x10, 0x50) and chunk[5] == 0xFB
            ):
                chunk = _refpack_decompress(chunk)
            else:
                chunk = zlib.decompress(chunk)
        if chunk[:4] != b'STBL':
            continue
        _, _, num_entries, _, _ = struct.unpack_from('<HBQHI', chunk, 4)
        spos = 21
        for _ in range(num_entries):
            k, _, slen = struct.unpack_from('<IBH', chunk, spos)
            spos += 7
            out[k] = chunk[spos:spos + slen].decode('utf-8', errors='replace')
            spos += slen
    return out


def load_stbl_dictionary(game_dir: Path = DEFAULT_GAME_DIR) -> dict[int, str]:
    global _stbl_cache
    if _stbl_cache is not None:
        return _stbl_cache
    if STBL_CACHE_PATH.exists():
        _stbl_cache = {
            int(k): v
            for k, v in json.loads(STBL_CACHE_PATH.read_text(encoding='utf-8')).items()
        }
        return _stbl_cache
    strings: dict[int, str] = {}
    if game_dir.exists():
        for pkg in sorted(game_dir.rglob('Strings_ENG_US.package')):
            strings.update(_read_package_stbls(pkg))
    if DEFAULT_MODS_DIR.exists():
        for pkg in sorted(DEFAULT_MODS_DIR.rglob('*.package')):
            try:
                strings.update(_read_package_stbls(pkg))
            except Exception:
                pass
    if strings:
        STBL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STBL_CACHE_PATH.write_text(json.dumps(strings, ensure_ascii=False), encoding='utf-8')
    _stbl_cache = strings
    return _stbl_cache


def resolve_stbl(string_id: int | None, actor: dict | None = None, target: dict | None = None) -> str | None:
    if not isinstance(string_id, int) or not string_id:
        return None
    raw = load_stbl_dictionary().get(string_id)
    if not raw:
        return None
    text = raw
    for idx, sim in (('0', actor), ('1', target)):
        if not sim:
            continue
        first_name = sim.get('name', '').split()[0] if sim.get('name') else ''
        full_name = sim.get('name', '')
        is_female = str(sim.get('gender', '')).upper() == 'FEMALE'
        text = text.replace('{' + idx + '.SimFirstName}', first_name)
        text = text.replace('{' + idx + '.SimName}', full_name)
        text = re.sub(
            r'\{M' + idx + r'\.([^{}]*)\}\{F' + idx + r'\.([^{}]*)\}',
            lambda m, fem=is_female: m.group(2 if fem else 1),
            text,
        )
        text = re.sub(
            r'\{F' + idx + r'\.([^{}]*)\}\{M' + idx + r'\.([^{}]*)\}',
            lambda m, fem=is_female: m.group(1 if fem else 2),
            text,
        )
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\{[^{}]*\}', '', text)
    text = ' '.join(text.split()).strip()
    if not text or '(should not be seen)' in text.lower():
        return None
    return text


def _clean_sim_for_prompt(sim: dict, partner: dict | None = None) -> dict:
    cleaned = {
        k: v for k, v in sim.items()
        if k not in ('id', 'trait_stbls', 'buffs', 'activities', 'voice_actor', 'voice_actor_muted', 'voice_pitch')
    }
    if sim.get('mood') and str(sim['mood']).startswith('Mood_'):
        cleaned['mood_label'] = str(sim['mood'])[5:]
    trait_labels = [
        label for label in (resolve_stbl(s, sim, partner) for s in sim.get('trait_stbls', []))
        if label
    ]
    if trait_labels:
        cleaned['trait_labels'] = trait_labels
    active_buffs = []
    for b in sim.get('buffs', []):
        name = resolve_stbl(b.get('name_stbl'), sim, partner)
        reason = resolve_stbl(b.get('reason_stbl'), sim, partner)
        entry = {'id': b.get('id')}
        if name:
            entry['name'] = name
        if reason:
            entry['reason'] = reason
        active_buffs.append(entry)
    if active_buffs:
        cleaned['active_buffs'] = active_buffs
    activity_labels = []
    for act in sim.get('activities', []):
        act_entry = {'id': act.get('id')}
        act_label = resolve_stbl(act.get('stbl'), sim, partner)
        if act_label:
            act_entry['label'] = act_label
        target_label = resolve_stbl(act.get('target_stbl'), sim, partner)
        if target_label:
            act_entry['target_label'] = target_label
        elif act.get('target'):
            act_entry['target'] = act['target']
        recipe_label = resolve_stbl(act.get('recipe_stbl'), sim, partner)
        if recipe_label:
            act_entry['recipe_label'] = recipe_label
        elif act.get('recipe'):
            act_entry['recipe'] = act['recipe']
        activity_labels.append(act_entry)
    if activity_labels:
        cleaned['activity_labels'] = activity_labels
    return cleaned


def build_scene(event: dict, recent_dialogue: list[str] | None = None) -> dict:
    actor = event['actor']
    target = event['target']
    scene: dict = {'interaction': event['interaction']}
    interaction_label = resolve_stbl(event.get('interaction_stbl'), actor, target)
    if interaction_label:
        scene['interaction_label'] = interaction_label
    if event.get('player_message'):
        scene['player_message'] = event['player_message']
    if event.get('hook_stage'):
        scene['hook_stage'] = event['hook_stage']
    if event.get('outcome'):
        scene['outcome'] = event['outcome']
    if event.get('venue'):
        scene['venue'] = event['venue']
    venue_label = resolve_stbl(event.get('venue_stbl'), actor, target)
    if venue_label:
        scene['venue_label'] = venue_label
    scene['actor'] = _clean_sim_for_prompt(actor, target)
    scene['target'] = _clean_sim_for_prompt(target, actor)
    if 'relationship' in event:
        rel = {k: v for k, v in event['relationship'].items() if k not in ('bit_stbls', 'bits')}
        rel['bits'] = [b for b in event['relationship'].get('bits', []) if ':' not in b]
        bit_labels = [
            label for label in (resolve_stbl(s, actor, target) for s in event['relationship'].get('bit_stbls', []))
            if label
        ]
        if bit_labels:
            rel['bit_labels'] = bit_labels
        scene['relationship'] = rel
    if recent_dialogue:
        scene['recent_dialogue'] = recent_dialogue[-3:]
    return scene


def select_voice(sim: dict, fallback_index: int = 0, used_male_voice: str | None = None) -> tuple[str, int]:
    gender = str(sim.get('gender', '')).upper()
    raw_pitch = float(sim.get('voice_pitch', 0.0) or 0.0)
    pitch_pct = max(-18, min(18, int(round(raw_pitch * 15))))
    if gender == 'FEMALE':
        return 'Microsoft Zira', pitch_pct
    male_voices = ('Microsoft David', 'Microsoft Mark')
    voice_actor = int(sim.get('voice_actor', 0) or 0)
    choice = male_voices[(voice_actor + fallback_index) % len(male_voices)]
    if used_male_voice and choice == used_male_voice:
        choice = male_voices[1] if used_male_voice == male_voices[0] else male_voices[0]
    return choice, pitch_pct


def _get_tts_worker() -> subprocess.Popen:
    global _tts_worker
    if _tts_worker is not None and _tts_worker.poll() is None:
        return _tts_worker
    ps_loop = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$ms = New-Object System.IO.MemoryStream; "
        "$s.SetOutputToWaveStream($ms); "
        "$s.Speak(' '); "
        "$s.SetOutputToNull(); "
        "$ms.Dispose(); "
        "[Console]::Out.WriteLine('READY'); [Console]::Out.Flush(); "
        "while (($line = [Console]::In.ReadLine()) -ne $null) { "
        "  $req = $line | ConvertFrom-Json; "
        "  $s.SetOutputToWaveFile($req.wav_path); "
        "  $s.SpeakSsml($req.ssml); "
        "  $s.SetOutputToNull(); "
        "  [Console]::Out.WriteLine('OK'); "
        "  [Console]::Out.Flush(); "
        "} "
        "$s.Dispose()"
    )
    _tts_worker = subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-Command', ps_loop],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
    )
    assert _tts_worker.stdout is not None
    _tts_worker.stdout.readline()
    return _tts_worker


def synthesize_dialogue_wav(text: str, actor: dict, target: dict, wav_path: Path) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    actor_voice, actor_pitch = select_voice(actor, 0)
    target_voice, target_pitch = select_voice(
        target, 1, used_male_voice=actor_voice if actor_voice != 'Microsoft Zira' else None
    )
    utterances = []
    for idx, line in enumerate(lines[:2]):
        spoken = line.split(':', 1)[1].strip() if ':' in line else line
        voice = actor_voice if idx == 0 else target_voice
        pitch = actor_pitch if idx == 0 else target_pitch
        utterances.append(
            f'<voice name="{voice}"><prosody pitch="{pitch:+d}%" rate="+4%">{html.escape(spoken)}</prosody></voice>'
        )
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
        + '<break time="180ms"/>'.join(utterances)
        + '</speak>'
    )
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    worker = _get_tts_worker()
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.write(json.dumps({'wav_path': str(wav_path), 'ssml': ssml}) + '\n')
    worker.stdin.flush()
    ack = worker.stdout.readline().strip()
    if ack != 'OK':
        raise RuntimeError(f'TTS worker failed: {ack}')
    return {
        'audio_file': str(wav_path),
        'actor_voice': {'voice': actor_voice, 'pitch_percent': actor_pitch},
        'target_voice': {'voice': target_voice, 'pitch_percent': target_pitch},
        'tts_elapsed_seconds': round(time.monotonic() - started, 3),
        'wav_bytes': wav_path.stat().st_size,
    }


def generate(
    event: dict,
    model: str,
    reasoning_effort: str | None = 'none',
    recent_dialogue: list[str] | None = None,
    tts_dir: Path | None = None,
) -> dict:
    api_key = os.environ['OPENROUTER_API_KEY']
    scene = build_scene(event, recent_dialogue=recent_dialogue)
    payload: dict = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': (ROOT / 'prompt.txt').read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
        ],
        'max_tokens': 300,
    }
    if reasoning_effort is not None:
        payload['reasoning'] = {'effort': reasoning_effort}
    request = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
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
    out = {
        'event_id': event['event_id'],
        'text': text,
        'scene_summary': {
            'interaction_label': scene.get('interaction_label'),
            'player_message': scene.get('player_message'),
            'outcome': scene.get('outcome'),
            'venue_label': scene.get('venue_label'),
            'actor_activities': scene['actor'].get('activity_labels'),
            'target_activities': scene['target'].get('activity_labels'),
        },
        'model': result.get('model', model),
        'reasoning_effort': reasoning_effort,
        'finish_reason': result['choices'][0].get('finish_reason'),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'usage': result.get('usage', {}),
    }
    if tts_dir is not None:
        wav_path = tts_dir / f"{event['event_id']}.wav"
        out['tts'] = synthesize_dialogue_wav(text, event['actor'], event['target'], wav_path)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path)
    parser.add_argument('--reply-file', type=Path,
                        help='Reply JSON path; defaults to <data-directory>/reply.json.')
    parser.add_argument('--once', type=Path, help='Generate once from a captured event JSON file.')
    parser.add_argument('--model', default='openai/gpt-6-luna')
    parser.add_argument('--reasoning-effort', default='none',
                        help='Explicit model reasoning effort; defaults to none for short dialogue.')
    parser.add_argument('--tts-dir', type=Path,
                        help='Optional directory to synthesize two-voice WAV audio for each exchange.')
    parser.add_argument('--speak', action='store_true',
                        help='Play synthesized WAV asynchronously when the game displays the notification.')
    args = parser.parse_args()
    if not os.environ.get('OPENROUTER_API_KEY'):
        parser.error('OPENROUTER_API_KEY is not set.')
    if args.once:
        print(json.dumps(
            generate(
                json.loads(args.once.read_text(encoding='utf-8-sig')),
                args.model,
                args.reasoning_effort,
                tts_dir=args.tts_dir,
            ),
            ensure_ascii=False,
            indent=2,
        ), flush=True)
        return
    if args.data_directory is None:
        parser.error('--data-directory is required unless --once is used.')

    data = args.data_directory
    reply_file = args.reply_file or (data / 'reply.json')
    reply_file.parent.mkdir(parents=True, exist_ok=True)
    tts_dir = args.tts_dir or (ROOT / '.local' / 'tts' if args.speak else None)
    events = data / 'events.jsonl'
    recent_by_zone: dict[str, list[str]] = {}

    load_stbl_dictionary()
    if tts_dir is not None:
        _get_tts_worker()
    with events.open('r', encoding='utf-8') as incoming:
        incoming.seek(0, os.SEEK_END)
        print(f'Listening for new AI-mode socials in {data} (reply={reply_file})', flush=True)
        while True:
            offset = incoming.tell()
            line = incoming.readline()
            if not line or not line.endswith('\n'):
                incoming.seek(offset)
                time.sleep(0.2)
                continue
            event = json.loads(line)
            if event.get('type') == 'displayed' and args.speak:
                audio_path = event.get('tts', {}).get('audio_file')
                if audio_path and os.path.exists(audio_path) and sys.platform == 'win32':
                    import winsound
                    winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                continue
            if event.get('type') not in ('social', 'player_chat') or event.get('mode') != 'ai':
                continue
            if time.time() - event['observed_at'] > 25:
                continue
            zone_key = str(event.get('venue') or 'default')
            recent = recent_by_zone.setdefault(zone_key, [])
            try:
                reply = generate(
                    event,
                    args.model,
                    args.reasoning_effort,
                    recent_dialogue=recent,
                    tts_dir=tts_dir,
                )
                recent.append(reply['text'])
                if len(recent) > 3:
                    del recent[:-3]
                print(f"{reply['elapsed_seconds']}s: {reply['text']}", flush=True)
            except urllib.error.HTTPError as error:
                reply = {'event_id': event['event_id'], 'error': f'HTTP {error.code}'}
                print(reply['error'], flush=True)
            except Exception as error:
                reply = {'event_id': event['event_id'], 'error': type(error).__name__}
                print(reply['error'], flush=True)
            temporary = reply_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, reply_file)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except KeyboardInterrupt:
        pass
