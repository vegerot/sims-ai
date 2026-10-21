"""Generate banter and realistic AI voices outside the game's legacy Python 3.7 thread.

Uses the checked-in project OpenRouter API key (DEFAULT_OPENROUTER_API_KEY) by default,
tracks session and cumulative costs (cost_summary.json + /api/v1/key), supports
1-speaker (solo_vocal, player_ask_self) and 2-speaker (social, player_chat) scenes,
and synthesizes trilingual (English / Hebrew / Russian) neural speech via openai/gpt-audio-mini.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import html
import json
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
import zlib


ROOT = Path(__file__).resolve().parent
DEFAULT_GAME_DIR = Path(r'C:\Program Files\EA Games\The Sims 4')
DEFAULT_MODS_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods')
STBL_CACHE_PATH = ROOT / '.local' / 'stbl_en_us.json'
DEFAULT_OPENROUTER_API_KEY = (
    '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'
)
DEFAULT_TTS_MODEL = 'openai/gpt-audio-mini'

_stbl_cache: dict[int, str] | None = None
_tts_worker: subprocess.Popen | None = None
_sim_voice_assignments: dict[str, str] = {}

FEMALE_OPENROUTER_VOICES = ('coral', 'nova', 'shimmer', 'sage', 'ballad', 'alloy')
MALE_OPENROUTER_VOICES = ('ash', 'echo', 'onyx', 'verse', 'fable')

VOICE_ACTOR_PREFERRED_VOICE = {
    1685527063: 'ash',      # ma (Male Adult A)
    1685527060: 'onyx',     # mb (Male Adult B)
    1685527061: 'verse',    # mc (Male Adult C)
    1802970394: 'coral',    # fa (Female Adult A)
    1802970393: 'nova',     # fb (Female Adult B)
    1802970392: 'shimmer',  # fc (Female Adult C)
    1802970399: 'sage',     # fd (Female Adult D)
    1853303385: 'alloy',    # ca (Child A)
    1853303382: 'ballad',   # cb (Child B)
}


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



class CostTracker:
    """Track per-call, per-session, and cumulative OpenRouter spend (text + TTS)."""

    def __init__(self, data_dir: Path | None, api_key: str):
        self.api_key = api_key
        self.data_dir = data_dir or (ROOT / '.local')
        self.summary_path = self.data_dir / 'cost_summary.json'
        self.session_started_at = time.time()
        self.session_chat_usd = 0.0
        self.session_tts_usd = 0.0
        self.session_chat_calls = 0
        self.session_tts_calls = 0
        self.session_exchanges = 0
        self.historical_chat_usd = 0.0
        self.historical_tts_usd = 0.0
        self.historical_chat_calls = 0
        self.historical_tts_calls = 0
        self.historical_exchanges = 0
        self.key_info: dict = {}
        self._load_or_seed_baseline()
        self.refresh_key_info()

    def _load_or_seed_baseline(self):
        if self.summary_path.exists():
            try:
                saved = json.loads(self.summary_path.read_text(encoding='utf-8'))
                cum = saved.get('cumulative') or {}
                self.historical_chat_usd = float(cum.get('chat_usd', 0.0))
                self.historical_tts_usd = float(cum.get('tts_usd', 0.0))
                self.historical_chat_calls = int(cum.get('chat_calls', 0))
                self.historical_tts_calls = int(cum.get('tts_calls', 0))
                self.historical_exchanges = int(cum.get('exchanges', 0))
                return
            except Exception:
                pass
        events_path = self.data_dir / 'events.jsonl'
        if events_path.exists():
            for line in events_path.read_text(encoding='utf-8', errors='replace').splitlines():
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                usage = ev.get('usage')
                if isinstance(usage, dict) and 'cost' in usage:
                    self.historical_chat_usd += float(usage.get('cost') or 0.0)
                    self.historical_chat_calls += 1
                    self.historical_exchanges += 1
                tts_info = ev.get('tts')
                if isinstance(tts_info, dict) and 'tts_cost_usd' in tts_info:
                    self.historical_tts_usd += float(tts_info.get('tts_cost_usd') or 0.0)
                    self.historical_tts_calls += int(tts_info.get('tts_calls', 1))

    def refresh_key_info(self) -> dict:
        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/key',
            headers={'Authorization': f'Bearer {self.api_key}'},
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8')).get('data') or {}
            self.key_info = {
                'label': data.get('label'),
                'usage_total_usd': round(float(data.get('usage') or 0.0), 6),
                'usage_daily_usd': round(float(data.get('usage_daily') or 0.0), 6),
                'limit_usd': data.get('limit'),
                'limit_remaining_usd': round(float(data.get('limit_remaining') or 0.0), 6)
                if data.get('limit_remaining') is not None else None,
            }
        except Exception:
            pass
        return self.key_info

    def record_exchange(self, chat_cost_usd: float, tts_cost_usd: float = 0.0, tts_calls: int = 0) -> dict:
        self.session_chat_usd += float(chat_cost_usd or 0.0)
        self.session_tts_usd += float(tts_cost_usd or 0.0)
        self.session_chat_calls += 1
        self.session_tts_calls += int(tts_calls)
        self.session_exchanges += 1
        self.refresh_key_info()
        summary = self.snapshot(last_chat_usd=chat_cost_usd, last_tts_usd=tts_cost_usd)
        self._save(summary)
        return summary

    def snapshot(self, last_chat_usd: float = 0.0, last_tts_usd: float = 0.0) -> dict:
        session_total = self.session_chat_usd + self.session_tts_usd
        cum_chat = self.historical_chat_usd + self.session_chat_usd
        cum_tts = self.historical_tts_usd + self.session_tts_usd
        cum_total = cum_chat + cum_tts
        return {
            'updated_at': time.time(),
            'last_exchange': {
                'chat_usd': round(float(last_chat_usd or 0.0), 6),
                'tts_usd': round(float(last_tts_usd or 0.0), 6),
                'total_usd': round(float((last_chat_usd or 0.0) + (last_tts_usd or 0.0)), 6),
            },
            'session': {
                'started_at': self.session_started_at,
                'exchanges': self.session_exchanges,
                'chat_calls': self.session_chat_calls,
                'tts_calls': self.session_tts_calls,
                'chat_usd': round(self.session_chat_usd, 6),
                'tts_usd': round(self.session_tts_usd, 6),
                'total_usd': round(session_total, 6),
            },
            'cumulative': {
                'exchanges': self.historical_exchanges + self.session_exchanges,
                'chat_calls': self.historical_chat_calls + self.session_chat_calls,
                'tts_calls': self.historical_tts_calls + self.session_tts_calls,
                'chat_usd': round(cum_chat, 6),
                'tts_usd': round(cum_tts, 6),
                'total_usd': round(cum_total, 6),
            },
            'openrouter_key': self.key_info,
        }

    def _save(self, summary: dict):
        try:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.summary_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, self.summary_path)
        except Exception:
            pass


def detect_message_language(text: str | None) -> str | None:
    if not text:
        return None
    if re.search(r'[\u0590-\u05FF]', text):
        return 'Hebrew (עברית)'
    if re.search(r'[\u0400-\u04FF]', text):
        return 'Russian (Русский)'
    return None


def choose_scene_language(
    event: dict,
    multilingual_chance: float = 0.12,
    language_override: str | None = None,
) -> str:
    if language_override:
        return language_override
    msg_lang = detect_message_language(event.get('player_message'))
    if msg_lang:
        return msg_lang
    if multilingual_chance > 0:
        r = random.random()
        if r < multilingual_chance / 2.0:
            return 'Hebrew (עברית)'
        if r < multilingual_chance:
            return 'Russian (Русский)'
    return 'English'


def build_scene(
    event: dict,
    recent_dialogue: list[str] | None = None,
    language: str = 'English',
) -> dict:
    actor = event['actor']
    target = event.get('target') if isinstance(event.get('target'), dict) else None
    actor_name = actor.get('name', 'Sim')
    target_name = target.get('name', 'Sim') if target else ''

    interaction_label = resolve_stbl(event.get('interaction_stbl'), actor, target)
    venue_label = resolve_stbl(event.get('venue_stbl'), actor, target)

    event_type = event.get('type', 'social')
    speaker_count = 1 if target is None or event_type in ('solo_vocal', 'player_ask_self') else 2
    action_desc = interaction_label or event.get('interaction', 'social')
    venue_desc = venue_label or event.get('venue') or 'the lot'

    if event_type == 'player_ask_self':
        summary = (
            f"The player asks {actor_name} directly: {event.get('player_message')!r} "
            f"at {venue_desc}. {actor_name} answers in the first person (1 line)."
        )
    elif event_type == 'solo_vocal' or speaker_count == 1:
        summary = (
            f"{actor_name} ({actor.get('mood', 'Fine')}) is performing solo vocal action "
            f"{action_desc!r} at {venue_desc} (outcome: {event.get('outcome') or 'SUCCESS'}). "
            f"Write 1 spoken line for {actor_name}."
        )
    elif event.get('player_message'):
        summary = (
            f"{actor_name} says to {target_name} at {venue_desc}: {event.get('player_message')!r}. "
            f"Line 1 is {actor_name}'s exact line; Line 2 is {target_name}'s response."
        )
    else:
        summary = (
            f"{actor_name} ({actor.get('mood', 'Fine')}) just performed {action_desc!r} "
            f"with {target_name} ({target.get('mood', 'Fine') if target else ''}) "
            f"at {venue_desc} (outcome: {event.get('outcome') or 'SUCCESS'})."
        )

    scene: dict = {
        'event_type': event_type,
        'speaker_count': speaker_count,
        'language': language,
        'summary': summary,
        'interaction': event.get('interaction'),
        'interaction_label': interaction_label,
        'outcome': event.get('outcome'),
        'venue': event.get('venue'),
        'venue_label': venue_label,
        'actor': _clean_sim_for_prompt(actor, target),
        'target': _clean_sim_for_prompt(target, actor) if target else None,
    }
    if target and isinstance(event.get('relationship'), dict):
        rel = {k: v for k, v in event['relationship'].items() if k not in ('bit_stbls', 'bits')}
        rel['bits'] = [b for b in event['relationship'].get('bits', []) if ':' not in b]
        bit_labels = [
            label for label in (resolve_stbl(s, actor, target) for s in event['relationship'].get('bit_stbls', []))
            if label
        ]
        if bit_labels:
            rel['bit_labels'] = bit_labels
        scene['relationship'] = rel

    if event.get('player_message'):
        scene['player_message'] = event['player_message']
    if recent_dialogue:
        scene['recent_dialogue'] = recent_dialogue[-3:]
    return scene


def select_openrouter_voice(sim: dict, slot: int = 0, avoid_voice: str | None = None) -> str:
    """Assign a consistent, distinct OpenAI neural voice per Sim."""
    sim_id = str(sim.get('id') or sim.get('name') or slot)
    cached = _sim_voice_assignments.get(sim_id)
    if cached and cached != avoid_voice:
        return cached

    gender = str(sim.get('gender') or '').upper()
    pool = FEMALE_OPENROUTER_VOICES if gender == 'FEMALE' else MALE_OPENROUTER_VOICES
    va = int(sim.get('voice_actor') or 0)
    preferred = VOICE_ACTOR_PREFERRED_VOICE.get(va)

    try:
        id_num = abs(int(sim.get('id') or 0))
    except ValueError:
        id_num = sum(ord(c) for c in sim_id)

    if preferred in pool:
        base_idx = (pool.index(preferred) + (id_num % len(pool))) % len(pool)
    else:
        base_idx = (id_num + slot) % len(pool)

    chosen = pool[base_idx]
    if chosen == avoid_voice:
        chosen = pool[(base_idx + 1) % len(pool)]

    _sim_voice_assignments[sim_id] = chosen
    return chosen


def select_sapi_voice(sim: dict, slot: int = 0) -> tuple[str, int]:
    """Select an installed Windows Desktop SAPI5 voice ('Microsoft David Desktop' or 'Microsoft Zira Desktop')."""
    gender = str(sim.get('gender') or '').upper()
    voice_actor = int(sim.get('voice_actor') or 0)
    raw_pitch = float(sim.get('voice_pitch') or 0.0)
    pitch_pct = max(-18, min(18, int(round(raw_pitch * 15))))
    if gender == 'FEMALE':
        offset = ((voice_actor % 5) - 2) * 3 if voice_actor else (-4 if slot == 0 else 4)
        return 'Microsoft Zira Desktop', max(-18, min(18, pitch_pct + offset))
    offset = ((voice_actor % 5) - 2) * 4 if voice_actor else (-5 if slot == 0 else 5)
    return 'Microsoft David Desktop', max(-18, min(18, pitch_pct + offset))


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


def synthesize_dialogue_sapi(text: str, actor: dict, target: dict | None, wav_path: Path) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    actor_voice, actor_pitch = select_sapi_voice(actor, 0)
    target_voice, target_pitch = (
        select_sapi_voice(target, 1) if isinstance(target, dict) else (actor_voice, actor_pitch)
    )
    max_lines = 1 if target is None else 2
    utterances = []
    for idx, line in enumerate(lines[:max_lines]):
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
        'engine': 'sapi',
        'audio_file': str(wav_path),
        'actor_voice': {'voice': actor_voice, 'pitch_percent': actor_pitch},
        'target_voice': {'voice': target_voice, 'pitch_percent': target_pitch} if target is not None else None,
        'tts_elapsed_seconds': round(time.monotonic() - started, 3),
        'tts_cost_usd': 0.0,
        'tts_calls': 0,
        'wav_bytes': wav_path.stat().st_size,
    }


def _normalize_dialogue_lines(raw_text: str, event: dict) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    actor_name = (event.get('actor') or {}).get('name') or 'Sim'
    target = event.get('target')
    target_name = target.get('name') if isinstance(target, dict) else None
    event_type = event.get('type', 'social')
    player_msg = (event.get('player_message') or '').strip()

    if target is None or event_type in ('solo_vocal', 'player_ask_self'):
        first = lines[0] if lines else ''
        spoken = first.split(':', 1)[1].strip() if ':' in first else first
        spoken = spoken.strip(' "“”*')
        return f'{actor_name}: {spoken}'

    if event_type == 'player_chat' and player_msg:
        reply_line = lines[-1] if lines else ''
        spoken_reply = reply_line.split(':', 1)[1].strip() if ':' in reply_line else reply_line
        spoken_reply = spoken_reply.strip(' "“”*')
        return f'{actor_name}: {player_msg}\n{target_name}: {spoken_reply}'

    out_lines = []
    for idx, ln in enumerate(lines[:2]):
        default_speaker = actor_name if idx == 0 else (target_name or 'Sim')
        if ':' in ln:
            spk, body = ln.split(':', 1)
            out_lines.append(f"{spk.strip('* ')}: {body.strip(' \"“”*')}")
        else:
            out_lines.append(f"{default_speaker}: {ln.strip(' \"“”*')}")
    return '\n'.join(out_lines)


def generate(
    event: dict,
    model: str,
    reasoning_effort: str | None = 'none',
    recent_dialogue: list[str] | None = None,
    tts_dir: Path | None = None,
    tts_engine: str = 'openrouter',
    multilingual_chance: float = 0.12,
    language_override: str | None = None,
    api_key: str = DEFAULT_OPENROUTER_API_KEY,
    cost_tracker: CostTracker | None = None,
) -> dict:
    language = choose_scene_language(event, multilingual_chance=multilingual_chance, language_override=language_override)
    scene = build_scene(event, recent_dialogue=recent_dialogue, language=language)
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
    raw_text = result['choices'][0]['message']['content'].strip()
    if not raw_text:
        raise ValueError('The model returned no dialogue.')
    if len(raw_text) > 1000:
        raise ValueError('The model exceeded the short-dialogue limit.')
    text = _normalize_dialogue_lines(raw_text, event)
    usage = result.get('usage', {})
    chat_cost_usd = float(usage.get('cost') or 0.0)

    out = {
        'event_id': event['event_id'],
        'event_type': event.get('type', 'social'),
        'speaker_count': scene['speaker_count'],
        'language': language,
        'text': text,
        'scene_summary': {
            'interaction_label': scene.get('interaction_label'),
            'player_message': scene.get('player_message'),
            'outcome': scene.get('outcome'),
            'venue_label': scene.get('venue_label'),
            'actor_activities': scene['actor'].get('activity_labels'),
            'target_activities': scene['target'].get('activity_labels') if scene.get('target') else None,
        },
        'model': result.get('model', model),
        'reasoning_effort': reasoning_effort,
        'finish_reason': result['choices'][0].get('finish_reason'),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'usage': usage,
    }

    tts_cost_usd = 0.0
    tts_calls = 0
    if tts_dir is not None:
        wav_path = tts_dir / f"{event['event_id']}.wav"
        tts_info = synthesize_dialogue_sapi(text, event['actor'], event.get('target'), wav_path)
        out['tts'] = tts_info
        tts_cost_usd = float(tts_info.get('tts_cost_usd') or 0.0)
        tts_calls = int(tts_info.get('tts_calls') or 0)

    if cost_tracker is not None:
        out['cost_summary'] = cost_tracker.record_exchange(
            chat_cost_usd=chat_cost_usd,
            tts_cost_usd=tts_cost_usd,
            tts_calls=tts_calls,
        )
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path, default=DEFAULT_MODS_DIR / 'BanterLab' / 'BanterLabData')
    parser.add_argument('--reply-file', type=Path,
                        help='Reply JSON path; defaults to <data-directory>/reply.json.')
    parser.add_argument('--once', type=Path, help='Generate once from a captured event JSON file.')
    parser.add_argument('--model', default='openai/gpt-6-luna')
    parser.add_argument('--reasoning-effort', default='none',
                        help='Explicit model reasoning effort; defaults to none for short dialogue.')
    parser.add_argument('--tts-dir', type=Path,
                        help='Optional directory to synthesize WAV audio for each exchange.')
    parser.add_argument('--tts-engine', choices=('sapi',), default='sapi',
                        help='TTS backend: sapi (Windows Desktop SAPI5).')
    parser.add_argument('--multilingual-chance', type=float, default=0.12,
                        help='Probability (0.0-1.0) of seasoning autonomous banter with Hebrew or Russian.')
    parser.add_argument('--language', default=None,
                        help='Optional explicit language override (e.g. "English", "Hebrew (עברית)", "Russian (Русский)").')
    parser.add_argument('--api-key', default=DEFAULT_OPENROUTER_API_KEY,
                        help='OpenRouter API key; defaults to the checked-in capped project key.')
    parser.add_argument('--speak', action='store_true',
                        help='Play synthesized WAV asynchronously when the game displays the notification.')
    args = parser.parse_args()

    if args.once:
        once_event = json.loads(args.once.read_text(encoding='utf-8-sig'))
        tracker = CostTracker(args.data_directory or (ROOT / '.local'), args.api_key)
        print(json.dumps(
            generate(
                once_event,
                args.model,
                args.reasoning_effort,
                tts_dir=args.tts_dir,
                tts_engine=args.tts_engine,
                multilingual_chance=args.multilingual_chance,
                language_override=args.language,
                api_key=args.api_key,
                cost_tracker=tracker,
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
    tracker = CostTracker(data, args.api_key)
    snap = tracker.snapshot()
    print(
        f"Cost tracker ready: cumulative=${snap['cumulative']['total_usd']:.6f} "
        f"({snap['cumulative']['exchanges']} exchanges) | "
        f"OpenRouter key remaining=${(snap['openrouter_key'].get('limit_remaining_usd') or 0):.4f}",
        flush=True,
    )
    if tts_dir is not None and args.tts_engine == 'sapi':
        _get_tts_worker()

    with events.open('r', encoding='utf-8') as incoming:
        incoming.seek(0, os.SEEK_END)
        print(
            f'Listening for AI events in {data} (model={args.model}, tts={args.tts_engine}, reply={reply_file})',
            flush=True,
        )
        while True:
            offset = incoming.tell()
            line = incoming.readline()
            if not line or not line.endswith('\n'):
                incoming.seek(offset)
                time.sleep(0.15)
                continue
            event = json.loads(line)
            if event.get('type') == 'displayed' and args.speak:
                audio_path = event.get('tts', {}).get('audio_file')
                if audio_path and os.path.exists(audio_path) and sys.platform == 'win32':
                    import winsound
                    winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                continue
            if event.get('type') not in ('social', 'player_chat', 'solo_vocal', 'player_ask_self') or event.get('mode') != 'ai':
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
                    tts_engine=args.tts_engine,
                    multilingual_chance=args.multilingual_chance,
                    language_override=args.language,
                    api_key=args.api_key,
                    cost_tracker=tracker,
                )
                recent.append(reply['text'])
                if len(recent) > 6:
                    del recent[:-6]
            except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
                reply = {'event_id': event['event_id'], 'error': str(exc)}
            temp = reply_file.with_suffix('.tmp')
            temp.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, reply_file)
            if 'cost_summary' in reply:
                cs = reply['cost_summary']
                tts_meta = reply.get('tts') or {}
                v1 = (tts_meta.get('actor_voice') or {}).get('voice')
                v2 = (tts_meta.get('target_voice') or {}).get('voice')
                print(
                    f"[{reply['event_id']}] lang={reply.get('language')} "
                    f"chat={reply.get('elapsed_seconds')}s tts={tts_meta.get('tts_elapsed_seconds')}s "
                    f"voices=({v1}, {v2}) | "
                    f"call=${cs['last_exchange']['total_usd']:.6f} "
                    f"session=${cs['session']['total_usd']:.6f} "
                    f"total=${cs['cumulative']['total_usd']:.6f}",
                    flush=True,
                )
            else:
                print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
