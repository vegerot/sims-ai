"""Unblind human-ratings.jsonl with eval/key.json: voice stars per engine, variety/fun per model+prompt, best/bad lines.

Each rater's latest value per item wins, like the page. "anonymous" is Max (rated before the name field was used).
Writes ratings-summary.json.
"""
import collections
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
key = json.loads((HERE / 'eval' / 'key.json').read_text(encoding='utf-8'))
tts = [json.loads(l) for l in (HERE / 'tts-results.jsonl').open(encoding='utf-8')]
auto = json.loads((HERE / 'session-summary.json').read_text(encoding='utf-8'))
RATERS = {'Mina': 'Mina', 'anonymous': 'Max'}

latest = {}  # (rater, section, item, candidate, kind) -> value
for l in (HERE / 'human-ratings.jsonl').open(encoding='utf-8'):
    r = json.loads(l)
    if r['rater'] in RATERS:
        latest[(RATERS[r['rater']], r['section'], r['item'], r['candidate'], r['kind'])] = r['value']

mean = lambda xs: round(statistics.mean(xs), 2) if xs else None
line_meta = {r['line']: (r['language'], r['kind']) for r in tts}
p50 = {m: statistics.median(r['ttlt_s'] for r in tts if r['model'] == m and 'ttlt_s' in r)
       for m in {r['model'] for r in tts if 'ttlt_s' in r}}
summary = {}

# 🎧 Voice: stars per engine, overall and split by kind/language.
voice = collections.defaultdict(lambda: collections.defaultdict(list))  # model -> bucket -> stars
pairs = []  # (Mina, Max) on the same clip, for agreement
for lid, letters in key['voice'].items():
    lang, kind = line_meta[lid]
    for letter, model in letters.items():
        got = {who: latest.get((who, 'voice', lid, letter, 'stars')) for who in RATERS.values()}
        for who, v in got.items():
            if v:
                for bucket in (who, f'{who} {kind}', f'{who} {lang}'):
                    voice[model][bucket].append(v)
        if got['Mina'] and got['Max']:
            pairs.append((got['Mina'], got['Max']))
summary['voice'] = {m: {'p50_s': round(p50[m], 2), **{b: [mean(v), len(v)] for b, v in sorted(b.items())}}
                    for m, b in voice.items()}
print(f"🎧 Voice engines, Mina's mean stars (n) | Max's | latency p50")
print(f"{'engine':38s} {'Mina':>9s} {'explicit':>9s} {'clean':>9s} {'en':>9s} {'he':>9s} {'ru':>9s} {'Max':>9s} {'p50':>6s}")
fmt = lambda b, k: f"{mean(b[k]) or '-'!s:>5}({len(b[k])})" if b.get(k) else f"{'-':>9s}"
for m, b in sorted(voice.items(), key=lambda kv: -(mean(kv[1]['Mina']) or 0)):
    print(f"{m:38s} " + ' '.join(f'{fmt(b, k):>9s}' for k in ('Mina', 'Mina explicit', 'Mina clean', 'Mina en', 'Mina he', 'Mina ru', 'Max'))
          + f" {p50[m]:6.2f}")
if pairs:
    a, b = zip(*pairs)
    r = statistics.correlation(a, b) if len(pairs) > 2 else float('nan')
    summary['voice_agreement'] = {'clips_both_rated': len(pairs), 'pearson': round(r, 2)}
    print(f"\nMina vs Max on the {len(pairs)} clips both rated: Pearson r = {r:.2f}")

# 🌙 Sessions: variety and fun per model+prompt, next to the automatic repetition counts.
print(f"\n🌙 Evenings (16 lines each): variety / fun, 1–5")
print(f"{'model:prompt':42s} {'Mina var':>8s} {'Mina fun':>8s} {'Max var':>8s} {'Max fun':>8s} {'rep.open':>8s} {'trigram':>8s}")
summary['session'] = {}
for sid, spec in sorted(key['session'].items(), key=lambda kv: -(latest.get(('Mina', 'session', kv[0], '*', 'variety')) or 0)
                        - (latest.get(('Mina', 'session', kv[0], '*', 'fun')) or 0) / 10):
    got = {f'{who} {kind}': latest.get((who, 'session', sid, '*', kind)) for who in RATERS.values() for kind in ('variety', 'fun')}
    a = auto.get(spec, {})
    summary['session'][spec] = {**got, 'repeated_openings': a.get('repeated_openings'), 'lines_reusing_a_trigram': a.get('lines_reusing_a_trigram')}
    print(f"{spec:42s} " + ' '.join(f"{got[k] if got[k] else '-'!s:>8}" for k in got) + f" {a.get('repeated_openings', '-')!s:>8} {a.get('lines_reusing_a_trigram', '-')!s:>8}")

# 💬 Lines: best picks and bad marks per candidate label (partial: only the rated cards count).
best = collections.Counter()
bad = collections.Counter()
shown = collections.Counter()
cards = collections.Counter()
for scene, letters in key['text'].items():
    for who in RATERS.values():
        pick = latest.get((who, 'text', scene, '*', 'best'))
        if not pick:
            continue
        cards[who] += 1
        for letter, label in letters.items():
            shown[(who, label)] += 1
            bad[(who, label)] += latest.get((who, 'text', scene, letter, 'bad')) == 1
        best[(who, letters[pick])] += 1
labels = sorted({label for letters in key['text'].values() for label in letters.values()})
summary['text'] = {who: {label: {'best': best[(who, label)], 'bad': bad[(who, label)], 'cards': shown[(who, label)]} for label in labels}
                   for who in RATERS.values()}
print(f"\n💬 Lines (partial: Mina rated {cards['Mina']}/31 cards, Max {cards['Max']}/31): ⭐ best / 👎 bad / cards shown")
for label in sorted(labels, key=lambda l: -best[('Mina', l)]):
    print(f"{label:18s} Mina {best[('Mina', label)]:>2}⭐ {bad[('Mina', label)]:>2}👎 /{shown[('Mina', label)]:<3} Max {best[('Max', label)]:>2}⭐ {bad[('Max', label)]:>2}👎 /{shown[('Max', label)]}")

(HERE / 'ratings-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')
