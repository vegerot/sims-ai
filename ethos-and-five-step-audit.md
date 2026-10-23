# 🔍 Sims birthday mod: ethos audit + five-step pass

Scope: everything in [gaming/sims-ai](README.md) — the original interview ([planning.md](planning.md)), the plan, 16 experiments, [companion.py](companion.py), the [in-game mod](src/banter_lab/__init__.py), [build.py](build.py), [prompt.txt](prompt.txt), and the live game log (`BanterLabData/events.jsonl`, 297 records, Oct 20 → Oct 21 9:02 PM).

Evidence labels used below: **🟢 observed** (measured or read directly), **🟡 inferred**, **⚪ not checked**.

---

## 🧾 TL;DR

1. **Days 1–2 were a model of the ethos.** Fixed line before generated text, one live observation per experiment, audio verified through loopback with speakers muted, a benchmark that overturned its own earlier wrong conclusion. 🎯
2. **Then it drifted.** Each "what's next?" added parts without a playtest in between. Code grew **11×** (301 → 3,431 non-empty lines). The newest ~950 lines (the save-aware stack) had **never run in the game** at the start of the audit: 0 of 297 game events contained the new fields. 🟢
3. **Two records overstated evidence.** Experiment 16's [result.json](experiments/16-solo-vocal-and-ask-self/result.json) listed a "captured" `solo_vocal` event and `vox_attempt` stats that **did not exist in the game log**, and reported the local compiler's Python 3.7.9, not the game's 3.7.0. 🟢 That was harness output recorded as live evidence.
4. **One instrument measured nothing.** The Simlish-replacement meter (`vox_attempt`) logged **0** events in the game, and `banter.status` printed **100%** coverage when the total was 0. 🟢
5. **Experiment 15 tested the wrong model.** It concluded that Gemini TTS wasn't on OpenRouter by calling the *chat* model `google/gemini-3.8-flash` ([result.json](experiments/15-cost-and-openrouter-tts/result.json)). The catalog lists `google/gemini-3.8-flash-tts` plus ~35 dedicated speech models. 🟢 A live probe got HTTP 200 for the exact line `gpt-audio-mini` refused, though it was ~1–2 s slower (details in Step 4).
6. **Outcome:** corrected the records (`6081c3de6550`), ran the Step 2 deletion pass (`3a4539bd342f`, `-1,254` lines), implemented selective Simlish muting + `_audio_until` overlap protection (`b6780621ec27`), and verified the save-aware stack across 7 live exchanges on a disposable copy of her save (`Kenya Bower` at `Boiling Point`).

---

## 🙇 Corrections to Turn 1

- ❌ Turn 1 claimed the companion was "actively heartbeating." **False.** The last heartbeat was **Oct 22, 1:01 AM**; no `python` or `TS4_x64` process was running. 🟢
- ❌ Turn 1 proposed six new features (situations, gossip trigger, Hebrew weights from "Hebrew-flavored names", pet narrator, 3-Sim cross-talk, birthday egg) on top of four features that had never run in-game. That is Step 3/4 work done before Steps 1–2.

---

## 1. 🌱 From the original idea to the audit

**The original brief** ([planning.md](planning.md)) said:

- A gift for Mina (1,000+ hours, likes relationships & drama → homes & restaurants → food, laughs while playing).
- "**Start small**." First feature: "watch Sims interact with funny English dialogue." Text first; speech is a separate experiment.
- The game chooses actions; the model only writes words.

**How the code grew** (non-empty lines, 🟢 from `sl cat`):

| Commit | What it was | companion.py | mod | prompt |
|---|---|---:|---:|---:|
| `98699fa` (Oct 20, 1 AM) | Working text prototype, 3 live exchanges | 102 | 199 | 15 |
| `138501a` (Oct 21) | Experiments 05–16: audio, STBL, UI, pie menu, TTS, cost tracking | 936 | 1,175 | 22 |
| `4dc5de4` (Oct 21, 9 PM) | Auto-launch, console logs, UI bytecode patches, lot-travel fixes | 1,057 | 1,428 | 24 |
| `1cb08ab` (Oct 22, 1 AM) | Save-aware stack (4 features) | **1,693** | **1,738** | 25 |
| `b678062` (Oct 22, 7:31 PM) | After Step 2 deletions + selective Simlish mute | **1,334** | **1,201** | 25 |

---

## 2. ⚖️ Ethos scorecard

### 🪶 Simplicity

**What's genuinely simple and good** ✅

- **Stdlib-only companion** with a two-file bridge: the game appends to `events.jsonl`, and the companion atomically replaces `reply.json`. No broker, no framework. Empneon, S4CL, and Lot51 were all *considered and rejected* with reasons.
- **A pure-stdlib STBL reader** (~175 lines) instead of a dependency. It resolves 176k strings and was verified live.
- **The pie menu is created at runtime** by subclassing a base-game interaction, so there is no `.package` tuning. The text input is a subclassed native dialog.
- **The words-only boundary** (game decides, model talks) eliminated the whole "world actions" track.
- **`prompt.txt` is reread per request**, so prompt iteration needs no rebuild.

**Where it drifted before Step 2 deletion** ❌ (all counts 🟢)

| Smell | Evidence | Fix (`3a4539bd342f` / `b6780621ec27`) |
|---|---|---|
| Too many entry points | **17** console commands, **12** CLI flags. The game always launches the companion with `--data-directory … --parent-pid …`. | Deleted 9 experiment-only console commands and 9 CLI flags. |
| The same fact sent 3 times | Relationship went to the model as `bits` + `bit_labels` + `highlights`. In the last real scene, `bit_labels` contained `Casual Discussion` ×4 and `Acquaintances` ×2. | De-duplicated `bit_labels` in `build_scene`. |
| Two of everything | 2 cost ledgers (local file + key `usage`). 2 TTS engines. 2 companion copies (repo + deployed to `Mods/`). | Deleted SAPI5, local cost ledger seeding, and duplicate deployed `companion.py` / `prompt.txt`. |
| A supervision subsystem | Heartbeat every 2 s, single-instance claim, PID kill via `ctypes`, spawn throttle, `--replace`, and `banter.companion` (~200 lines). | Replaced with `msvcrt.locking` on `.local/companion.lock` and `--parent-pid`. |

### 🛡️ Paranoia

- **Mod had 44 `except` clauses, 18 of them `except Exception: pass` (silent).** 🟢
- **Justified:** one try/except at each **hook boundary**, because an exception inside `Interaction` hooks could break her game.
- **Not justified:** the *inner* silent excepts inside snapshot helpers, which hid broken APIs (`vox_attempt` stayed at 0 forever while `status` printed `100.0%`). Replaced with `_record_error()`, which logs each unique traceback once to `events.jsonl`.
- **SAPI fallback:** fired when OpenRouter TTS failed, replacing the *other* Sim's good neural voice with a robot voice on a single-line content refusal. Deleted in `3a4539bd342f`; TTS now runs per line with `_transcript_matches` (60% word overlap), leaving only a refused line silent.

### 🧪 Experiment-driven design

| Claim in records | What the game log showed 🟢 | Resolution |
|---|---|---|
| Exp 16: `solo_shout_forbidden_words_captured` (`solo-1792608909001-1`), `vox_attempt_telemetry: {total: 1}` | Generated by local Python 3.7.9 mock harness in `.local/test-exp16-data`, not the game (Python 3.7.0). Ask Self was observed live (4 events); Shout Forbidden Words was not. | Corrected [experiments/16/result.json](experiments/16-solo-vocal-and-ask-self/result.json) and [progress.md](progress.md) (`6081c3de6550`). |
| Archive: save-aware stack "verified against the Sims and storylines from her saves" | Initially verified only against offline-decoded saves (0 game events). | Corrected archive wording (`6081c3de6550`), then verified live in-game across 7 exchanges on `Kenya Bower`'s save at `Boiling Point`. |
| "Simlish replacement rate is directly measurable via `banter.status`" | `vox_attempt` never fired (social Simlish is played by animation clips in C++, not Python `PlaySound.start`). | Deleted `vox_attempt` (`3a4539bd342f`). |
| Exp 15: "Gemini 3.8 Flash can't output audio on OpenRouter" | Tested chat model `google/gemini-3.8-flash` instead of `google/gemini-3.8-flash-tts`. | Annotated [experiments/15/result.json](experiments/15-cost-and-openrouter-tts/result.json); kept `openai/gpt-audio-mini` per Max's decision. |

---

## 3. 🧭 Max's 4 Decisions & Implementation

1. **Selective Simlish Mute:** *"Mute the Simlish that's replaced with English. For Simlish that hasn't been replaced with English yet, keep it."*
   - Implemented in [src/banter_lab/__init__.py](src/banter_lab/__init__.py) (`b6780621ec27`): `_submit(event, *sims)` calls `_mute_replaced` (`_muted_until[sim_id]`), and `_ReplyPoller.poll` sets the unmute deadline to `now + audio_dur + 0.5 s` (or `0.0` on silent/error replies) while `_busy()` holds `_audio_until = now + audio_dur` (`skip_reason: "audio_playing"`) so overlapping autonomous socials play their natural Simlish without cutting off active English WAV playback.
2. **Line Shape:** *"Keep the two-line exchanges."*
3. **Live Playtest:** *"Yes. Use CUA to playtest."*
4. **TTS Engine:** *"No. Keep OpenAI."*
