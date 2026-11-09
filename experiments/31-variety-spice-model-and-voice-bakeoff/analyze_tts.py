"""Summarize tts-results.jsonl per model: success and verbatim match by kind and language, latency."""
import collections
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = [json.loads(l) for l in (HERE / 'tts-results.jsonl').open(encoding='utf-8')]
by = collections.defaultdict(list)
for r in rows:
    by[r['model']].append(r)


def frac(rs):
    ok = sum(1 for r in rs if r.get('matches'))
    return f'{ok}/{len(rs)}'


print(f"{'model':38s} {'clean':>6s} {'explic':>6s} {'en':>5s} {'he':>5s} {'ru':>5s} {'p50':>5s} {'p90':>5s}  errors")
summary = {}
for m, rs in sorted(by.items()):
    lat = sorted(r['ttlt_s'] for r in rs if 'ttlt_s' in r)
    p50 = statistics.median(lat) if lat else float('nan')
    p90 = lat[int(0.9 * (len(lat) - 1))] if lat else float('nan')
    k = {kind: frac([r for r in rs if r['kind'] == kind]) for kind in ('clean', 'explicit')}
    lg = {lang: frac([r for r in rs if r['language'] == lang]) for lang in ('en', 'he', 'ru')}
    errs = collections.Counter(r['error'][:60] for r in rs if r.get('error'))
    summary[m] = dict(**k, **lg, p50=p50, p90=p90, errors=dict(errs))
    print(f"{m:38s} {k['clean']:>6s} {k['explicit']:>6s} {lg['en']:>5s} {lg['he']:>5s} {lg['ru']:>5s} {p50:5.2f} {p90:5.2f}  {dict(errs) if errs else ''}")
(HERE / 'tts-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')
mism = [r for r in rows if 'audio_file' in r and not r.get('matches')]
print(f'\n{len(mism)} audio files whose transcript did not match:')
for r in mism:
    print(f"  {r['model']:36s} {r['line']:12s} {(r.get('transcript') or r.get('transcript_error') or '')[:80]!r}")
