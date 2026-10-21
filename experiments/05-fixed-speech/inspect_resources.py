"""Read-only mapping of animation voice cues to base-game audio resources.

Run with python3.15. Imports the user's existing local package reader.
Does not launch the game, load the downloaded Sound Tool, or inspect saves.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import wave

READER_REPO = Path(r'C:\Users\Max\code\github.com\sims\sims4-workspace')
sys.path.insert(0, str(READER_REPO))
from util.datamining.package_reader import PackageReader

GAME = Path(r'C:\Program Files\EA Games\The Sims 4')
HERE = Path(__file__).resolve().parent


def fnv1_64(name: str) -> int:
    value = 0xCBF29CE484222325
    for byte in name.lower().encode('utf-8'):
        value = ((value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF) ^ byte
    return value


def main() -> None:
    # Match the sound-name/hash example published by the tool's creator.
    assert fnv1_64('voact_actinggig_havedrinkwith_riskysuccess_x_a1skill_fa') == 0xC1230D4B11426834
    path = GAME / 'Data/Client/ClientFullBuild1.package'
    package = PackageReader(str(path))
    package.read()
    counts = Counter(entry.key.type_id for entry in package.entries)
    configs = {entry.key.instance: entry for entry in package.entries
               if entry.key.type_id == 0xFD04E3BE}
    matches = []
    for cue in ['vo_expr_greet_angry_25f', 'vo_expr_greet_uncomfortable_45f',
                'vo_expr_greet_bored_40f', 'vo_expr_greet_sad_25f']:
        for voice in ['ma', 'mb', 'mc', 'fa', 'fc', 'fd', 'tma', 'tmb', 'tmc', 'tfa', 'tfc', 'tfd']:
            name = cue + '_' + voice
            entry = configs.get(fnv1_64(name))
            if entry is not None:
                data = package.extract_resource(entry)
                assert len(data) == entry.mem_size
                matches.append({'name': name, 'resource': str(entry.key),
                                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    with wave.open(str(HERE / 'audio/fixed-hello.wav')) as clip:
        duration = clip.getnframes() / clip.getframerate()
        audio = {'text': 'Oh. Hello.', 'voice': 'Microsoft Zira Desktop - English (United States)',
                 'duration_seconds': round(duration, 3), 'sample_rate': clip.getframerate(),
                 'channels': clip.getnchannels(), 'sample_width_bytes': clip.getsampwidth()}
    result = {
        'experiment': 'Fixed English speech: offline resource mapping and test clip',
        'game_build': '1.128.90.1030',
        'package': str(path.relative_to(GAME)),
        'resource_counts': {f'{key:08X}': counts[key]
                            for key in [0xFD04E3BE, 0x01A527DB, 0x01EEF63A]},
        'config_matches': matches,
        'english_test_clip': audio,
        'sound_tool': {
            'release': '1.1.29',
            'creator_page': 'https://modthesims.info/d/639090/ts4-sound-tool.html',
            'archive_sha256': '8DF99B31AC5E14A6E81A836BCC775E67B38BBAA2A3371CB8B982BDBEA662C0BF',
            'downloaded': True,
        },
        'limits': [
            'Base resources only; patch and mod overrides have not been resolved.',
            'Cue names were found in base animation clips; no live cue trigger was observed.',
            'No packaged English resource, replacement, selective suppression, or gameplay test yet.',
            'Sound Tool is an offline asset utility, not TTS or a selected runtime dependency.',
        ],
    }
    (HERE / 'resource-map.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'audio_config_matches': len(matches), 'test_clip': audio}, indent=2))


if __name__ == '__main__':
    main()
