# 🔍 Sims birthday mod: ethos audit + five-step pass

Scope: everything in [gaming/sims-ai](README.md) — the original interview ([planning.md](planning.md)), the plan, 17 experiments, [companion.py](companion.py), the [in-game mod](src/banter_lab/__init__.py), [build.py](build.py), [prompt.txt](prompt.txt), and the live game log (`BanterLabData/events.jsonl`).

Evidence labels used below: **🟢 observed** (measured or read directly), **🟡 inferred**, **⚪ not checked**.

---

## 🧾 TL;DR

1. **Days 1–2 were a model of the ethos.** Fixed line before generated text, one live observation per experiment, audio verified through loopback with speakers muted, a benchmark that overturned its own earlier wrong conclusion. 🎯
2. **Then it drifted.** Each "what's next?" added parts without a playtest in between. Code grew **11×** (301 → 3,431 non-empty lines). The newest ~950 lines (the save-aware stack) had **never run in the game** at the start of the audit: 0 of 297 game events contained the new fields. 🟢
3. **Two records overstated evidence.** Experiment 16's [result.json](experiments/16-solo-vocal-and-ask-self/result.json) listed a "captured" `solo_vocal` event and `vox_attempt` stats that **did not exist in the game log**, and reported the local compiler's Python 3.7.9, not the game's 3.7.0. 🟢 That was harness output recorded as live evidence.
4. **One instrument measured nothing.** The Simlish-replacement meter (`vox_attempt`) logged **0** events in the game, and `banter.status` printed **100%** coverage when the total was 0. 🟢
5. **Experiment 15 tested the wrong model.** It concluded that Gemini TTS wasn't on OpenRouter by calling the *chat* model `google/gemini-3.8-flash` ([result.json](experiments/15-cost-and-openrouter-tts/result.json)). The catalog lists `google/gemini-3.8-flash-tts` plus ~35 dedicated speech models. 🟢 A live probe got HTTP 200 for the exact line `gpt-audio-mini` refused ([Experiment 18](experiments/18-openrouter-tts-endpoint-benchmark/result.json) verified all 4 scratch clips via `google/gemini-3.8-flash` audio transcription and added a 14-line per-line refusal fallback to `google/gemini-3.8-flash-lite-tts`).
6. **Outcome:** Corrected the records (`6081c3de6550`), ran two deletion/simplification passes (`3a4539bd342f` and today's follow-up), implemented selective Simlish muting + `_audio_until` overlap protection (`b6780621ec27`), verified the save-aware stack + pet banter (`meimei`) + multi-exchange `pair_memory` + notification `timeout_duration` live on her save (`Slot_00000002.save`), ran the [5-scene A/B experiment](experiments/17-humanize-tables-ab/result.json) that deleted the 389-line `humanize_*` tables, and shelved the `Dialog.gfx` `Enter`-to-send bytecode patch. Total code dropped from **4,049 total lines (`1cb08ab`) → 1,820 total lines (`-55.1%`)**.

---

## 1. 🌱 How the code grew and shrank

| Commit | What it was | companion.py | mod (`__init__.py`) | build.py | prompt.txt |
|---|---|---:|---:|---:|---:|
| `98699fa` (Oct 20, 1 AM) | Working text prototype, 3 live exchanges | 102 | 199 | — | 15 |
| `1cb08ab` (Oct 22, 1 AM) | Peak bloat before audit (total lines) | **1,827** | **1,908** | **285** | **29** |
| `b678062` (Oct 22, 7:31 PM) | After Agy Step 2 deletions + selective mute | 1,334 | 1,201 | 285 | 29 |
| **Current (Oct 23, 2:00 AM)** | **After Step 2/3/4/5 + Exp 18 & 19 + replay set** | **778** | **800** | **226** | **27** |

---

## 2. 🚀 Five-step pass & completion status

### Step 1 — Make the requirements less dumb

| Requirement | Owner | Verdict & Status |
|---|---|---|
| A delightful gift on **Oct 29** | Max | ✅ Core goal. |
| Funny English dialogue during real socials | Max | ✅ Verified live on her save (`Boiling Point` and `3 Sequoia Cottage`). |
| Words only; the game decides actions | Max | ✅ Preserved. |
| Selective Simlish mute (mute only Sims whose lines are replaced with English) | Max | ✅ Implemented & verified (`_mute_replaced` / `_muted_until`). |
| Notification timeout = `audio + 2 s` | Max | ✅ Verified live (`Notifications.gfx` `mid=6609` patch; `12.53 s` card auto-dismissed on schedule). |
| `Enter`-to-send inside text input dialogs | Max | ⏸️ **Shelved.** Scaleform CLIK's `FocusHandler` bypasses `TextInput.handleInput` when `mcTextInput.focused = 1` is set directly; shelving `Enter`-to-send deleted 65 lines of raw ActionScript 3 hex patches (`Dialog.gfx`) from `build.py` and shrank `BanterLabUI.package` by 52%. Clicking `OK` works reliably. |

### Step 2 — Delete the part or process step

| Part | ~Lines | Status |
|---|---:|---|
| 13 redundant console commands (`start`, `trace`, `test`, `audio`, `summon`, `say`, `solo`, `menu`, `companion`, `ai`, `talk`, `ask`, `mute`) | ~350 | ✅ **Deleted.** Kept only `banter.status`, `banter.logs`, `banter.reload`, and `banter.stop`; all player controls live on Page 1 of the Sim Pie Menu. |
| SAPI5 fallback engine + PowerShell worker | ~100 | ✅ **Deleted.** Each line synthesizes independently via `openai/gpt-audio-mini`; a refused line automatically retries on `google/gemini-3.8-flash-lite-tts` via `/api/v1/audio/speech` (`GEMINI_VOICE_MAP`). |
| `vox_attempt` hook + `_vox_stats` + 3 s cooldown | ~60 | ✅ **Deleted.** |
| Local `CostTracker` ledger seeding + per-exchange `/api/v1/key` poll | ~105 | ✅ **Deleted.** `GET /api/v1/key` runs once at startup; session cost sums `usage.cost`. |
| Heartbeat file churn (`companion_heartbeat.json`) + PID kill supervision + duplicate `Mods/` copies | ~180 | ✅ **Deleted.** Replaced with `msvcrt.locking` on `.local/companion.lock` and `--parent-pid` auto-exit (verified live twice). |
| `MemoryStore` seeding migration + `recent_dialogue` second memory | ~70 | ✅ **Deleted.** `pair_memory` (`BanterLabData/memories.json`) is the single memory store. |
| 6 hand-written `humanize_*` translation tables + `bits`/`bit_labels`/`highlights` triple | ~420 | ✅ **Deleted after 5-scene A/B test ([experiments/17-humanize-tables-ab/result.json](experiments/17-humanize-tables-ab/result.json)).** `openai/gpt-6-luna` reads STBL labels + filtered raw tuning names (`trait_PetQuirk_Obsessed_Computer`, `career_OddJob`, `romantic-HasBeenUnfaithful`) natively. |
| `Dialog.gfx` `Enter`-to-send bytecode patches in `build.py` | ~65 | ✅ **Deleted (shelved).** |

### Step 3 — Simplify what survives

- **Single memory (`pair_memory`):** Verified multi-exchange persistence in `BanterLabData/memories.json` across `Kenya Bower :: Olive Tinker` (6 exchanges) and `Kenya Bower :: meimei` (2 exchanges at `3 Sequoia Cottage`).
- **Outer-boundary error handling only:** Removed redundant inner `try/except` wrappers inside `_sim_activities`, `_sim_careers`, `_sim_skills`, `_sim_snapshot`, `_sim_social_connections`, and `_venue_snapshot`; the 5 outer hook/callback entry points log any unique traceback once to `events.jsonl` via `_record_error()`.
- **Tighter prompt (`prompt.txt`):** Removed the 17-field catalog list and tightened line length to `5–13 words per line` so voiced audio fits social animation timing.
