"""Repetition across a simulated session: templates, repeated openings, repeated props, and n-gram reuse."""
import collections
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = [json.loads(l) for l in (HERE / 'session-results.jsonl').open(encoding='utf-8')]
MOOD_LIST = re.compile(r"\b(I['’]m|I am|She['’]s|He['’]s|You['’]re)\s+\w+,\s+\w+(,| and)")
SOMEHOW = re.compile(r',\s*(and|but)\s+(somehow|still)\b', re.I)
SETUP_PUNCH = re.compile(r'^[^.!?]{8,}[.!?]\s+\S.*[.!?]$')  # "Setup. Punchline." two-sentence shape
STOP = set('the a an and or but to of in on at for with my your you i me it is are was be this that so just not im i’m you’re it’s'.split())


def words(s):
    return re.findall(r"[\w’']+", s.lower())


summary = {}
print(f"{'model:prompt':40s} {'lines':>5s} {'moodL':>5s} {'some':>4s} {'2sent':>5s} {'open2':>5s} {'tri':>5s}  top repeated words")
for spec in sorted({f"{r['model']}:{r['prompt']}" for r in rows}):
    rs = [r for r in rows if f"{r['model']}:{r['prompt']}" == spec and r.get('text')]
    lines = [l.split(':', 1)[-1].strip() for r in rs for l in r['text'].splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith(('Woof', 'Meow'))]
    n = len(lines)
    mood = sum(bool(MOOD_LIST.search(l)) for l in lines)
    some = sum(bool(SOMEHOW.search(l)) for l in lines)
    two = sum(bool(SETUP_PUNCH.search(l)) for l in lines)
    opens = collections.Counter(' '.join(words(l)[:2]) for l in lines)
    open_rep = sum(v for v in opens.values() if v > 1)
    tri_seen, tri_rep = set(), 0
    for l in lines:
        w = words(l)
        tris = {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
        tri_rep += bool(tris & tri_seen)
        tri_seen |= tris
    content = collections.Counter(w for l in lines for w in set(words(l)) if w not in STOP and len(w) > 3)
    top = ', '.join(f'{w}×{k}' for w, k in content.most_common(6))
    summary[spec] = dict(lines=n, mood_list=mood, somehow_still=some, setup_punchline=two,
                         repeated_openings=open_rep, lines_reusing_a_trigram=tri_rep, top_words=content.most_common(10))
    pct = lambda x: f'{100 * x / max(n, 1):4.0f}%'
    print(f'{spec:40s} {n:5d} {pct(mood):>5s} {pct(some):>4s} {pct(two):>5s} {pct(open_rep):>5s} {pct(tri_rep):>5s}  {top}')
(HERE / 'session-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')
