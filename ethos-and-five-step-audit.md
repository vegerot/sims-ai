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
6. **Outcome:** Corrected the records (`6081c3de6550`), ran two deletion/simplification passes (`3a4539bd342f` and today's follow-up), implemented selective Simlish muting + `_audio_until` overlap protection (`b6780621ec27`), verified the save-aware stack + pet banter (`meimei`) + multi-exchange `pair_memory` + notification `timeout_duration` live on her save (`Slot_00000002.save`), ran the [5-scene A/B experiment](experiments/17-humanize-tables-ab/result.json) that deleted the 389-line `humanize_*` tables, and shelved the `Dialog.gfx` `Enter`-to-send bytecode patch. Total code dropped from **4,049 total lines (`1cb08ab`) → 1,894 total lines (`-53.2%`)**.

---

## 1. 🌱 How the code grew and shrank

| Commit | What it was | companion.py | mod (`__init__.py`) | build.py | prompt.txt |
|---|---|---:|---:|---:|---:|
| `98699fa` (Oct 20, 1 AM) | Working text prototype, 3 live exchanges | 102 | 199 | — | 15 |
| `1cb08ab` (Oct 22, 1 AM) | Peak bloat before audit (total lines) | **1,827** | **1,908** | **285** | **29** |
| `b678062` (Oct 22, 7:31 PM) | After Agy Step 2 deletions + selective mute | 1,334 | 1,201 | 285 | 29 |
| `e8c92a4` (Oct 23, 3:55 AM) | After first Step 2–5 pass & Exp 17–20 (`1,894` total lines) | 837 | 807 | 225 | 25 |
| **Current (Oct 29, Birthday Release)** | **After Iterations 4–10 (pet SAPI5, EN/HE/RU, Thoughts, Phone, Drama/Text/Renovation, `-18.5 dBFS`, symbolic `DoABC` patcher) + 2nd Five-Step audit (`2,943` total lines, `-27.3%` below peak)** | **1,224** | **1,186** | **503** | **30** |

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
| SAPI5 fallback for human speech | ~100 | ✅ **Deleted for humans; scoped to pets by user request.** Humans synthesize via `openai/gpt-audio-mini` with per-line refusal fallback to `google/gemini-3.8-flash-lite-tts`; cats & dogs intentionally speak their English `[collar translation]` in robotic Windows SAPI5 (`Zira`/`David`) while keeping unmuted real barks/meows. |
| `vox_attempt` hook + `_vox_stats` + 3 s cooldown + `_SOLO_VOCAL_STBLS` + `_on_interaction_start` hook | ~90 | ✅ **Deleted.** Both `vox_attempt` and `solo_vocal` had `0` events in `events.jsonl`, and removing `_solo_vocal_actor` eliminated the global `Interaction._trigger_interaction_start_event` hook completely. |
| Local `CostTracker` ledger seeding + per-exchange `/api/v1/key` poll | ~105 | ✅ **Deleted.** `GET /api/v1/key` runs once at startup; session cost sums `usage.cost`. |
| Heartbeat file churn (`companion_heartbeat.json`) + PID kill supervision + duplicate `Mods/` copies | ~180 | ✅ **Deleted.** Replaced with `msvcrt.locking` on `.local/companion.lock` and `--parent-pid` auto-exit (verified live twice). |
| `MemoryStore` seeding migration + `recent_dialogue` second memory | ~70 | ✅ **Deleted.** `pair_memory` (`BanterLabData/memories.json`) is the single memory store. |
| 6 hand-written `humanize_*` translation tables + `bits`/`bit_labels`/`highlights` triple | ~420 | ✅ **Deleted after 5-scene A/B test ([experiments/17-humanize-tables-ab/result.json](experiments/17-humanize-tables-ab/result.json)).** `openai/gpt-6-luna` reads STBL labels + filtered raw tuning names (`trait_PetQuirk_Obsessed_Computer`, `career_OddJob`, `romantic-HasBeenUnfaithful`) natively. |
| `Dialog.gfx` `Enter`-to-send bytecode patches in `build.py` | ~65 | ✅ **Deleted (shelved).** |

### Step 3 — Simplify what survives

- **Single memory (`pair_memory`):** Verified multi-exchange persistence in `BanterLabData/memories.json` across `Kenya Bower :: Olive Tinker` (6 exchanges) and `Kenya Bower :: meimei` (2 exchanges at `3 Sequoia Cottage`).
- **Outer-boundary error handling only:** Removed redundant inner `try/except` wrappers inside `_sim_activities`, `_sim_careers`, `_sim_skills`, `_sim_snapshot`, `_sim_social_connections`, and `_venue_snapshot`; the 5 outer hook/callback entry points log any unique traceback once to `events.jsonl` via `_record_error()`.
- **Tighter prompt (`prompt.txt`):** Removed the 17-field catalog list and tightened line length to `5–13 words per line` so voiced audio fits social animation timing.

---

## 3. 🎂 October 29 Birthday-Release Audit (`AGENTS.md` + Second Five-Step Pass)

Between Oct 23 (`1,894` lines) and Oct 28, Iterations 4–9 added 9 user-facing gameplay features (Windows SAPI5 pet collar voices, ~12% playful Hebrew/Russian seasoning, 1-click `Hear Thoughts`, off-lot `Call / Text Someone`, automatic `Drama reaction`, post-drama `Sim text`, Build/Buy `Renovation reaction`, `nearby_sims` + `gossip`, `-18.5 dBFS` RMS normalization, and the patch-resilient symbolic `DoABC` `Notifications.gfx` patcher in `build.py` for EA patch `1.129.39.1030`). Re-auditing 100% of the codebase against global `AGENTS.md`, [CONTEXT.md](CONTEXT.md), and the **Two-Question Dialogue Benchmark** (*"Is the dialogue funny?"* and *"Does it make sense for the character to say this in their current in-game situation?"*) caught and eliminated a second wave of complexity drift ([Experiment 30](experiments/30-dialogue-benchmark-five-step-audit-and-live-verification/result.json)):

| Finding | Mechanism & Fix | Status |
|---|---|---|
| **Re-introduced `_FAMILY_TARGET_ROLES` humanize table + inverted `reverse_bits`** | Sims 4 stores every directional bit on `owner`'s `RelationshipTracker` with `Actor = owner` and `Target = other` (`family_Target_IsParentOf_Actor`, `relBit_MultiUnit_TenantToLandlord`, `sentimentBit_Actor_BitterAt_Target_ST_breakup`). Emitting raw `reverse_bits` without substituting `Actor`/`Target` inverted parent/child (`Jay Robles` misread as `"Mom"`) and landlord/tenant roles. Deleted the 14-row `_FAMILY_TARGET_ROLES` table, `_humanize_family_bit`, 9-arg `_filter_bits`, and `reverse_bits` output (~50 lines); replaced with 7-line `_orient_bit(bit, owner_first, other_first)` + `_merged_bits`. | ✅ **Verified (`3/3` offline + live `aurora_is_tenant_of_Panya`).** |
| **Static rent/mold/appliance prompt pollution** | Non-home scenes at `11C Sungai Point` previously received `lot_value`, `lot_rooms`, passive `susceptibleToMold`/`Haunted`, `daily_rent: 129`, and TV SKU `"InvisiView Flat Panel Tabletop TV"`, making Sims obsess over rent/mold and recite catalog SKUs during casual flirty chats. Gated static home metadata on `about_home`, suppressed catalog SKUs on already-labelled activities (`"Watch Romance"`) while preserving book/food titles, filtered `trait_Attraction_*` calculator weights + `buff_Want_Gained_*` meta-buffs, and banned `;` in `prompt.txt`. | ✅ **Verified live (`chat-1793272550305-6` vs `chat-1793274139757-7`).** |
| **Unused 3-Sim `bystander` (`0/146` real hits)** | Over-engineered 3-speaker chime-in path never fired once in real play (`0/146` events). Deleted `bystander` end-to-end across `__init__.py`, `companion.py`, `prompt.txt`, and `CONTEXT.md`; replaced with 2-Sim post-drama `drama_reaction` when the partner is still within `12 m`. | ✅ **Deleted & verified.** |
| **Over-engineered `--once` graph bucketing + `MemoryStore._lock`** | Live `companion.py` is 100% single-threaded; the 34-line union-find connected-component bucketer and `threading.Lock` existed solely for batch `--once <dir>` runs. Restored a 9-line sequential `--once` loop and lock-free `MemoryStore`. | ✅ **Deleted (~38 lines).** |
| **Cross-layer `companion.py -> import build` shutdown hook + non-atomic builds** | `companion.py` imported `build.py` on shutdown to rebuild `BanterLabUI.package`, coupling runtime IPC to build tooling. Deleted the shutdown hook and made `build.py` write `BanterLab.ts4script` and `BanterLabUI.package` atomically via `.tmp` + `os.replace`. | ✅ **Deleted & hardened.** |
| **Paranoid `getattr`/`hasattr` defensive wrappers & subtle state races** | Removed ~145 redundant `getattr`/`hasattr` wrappers across `src/banter_lab/__init__.py` (relying on outer-boundary `_record_error()`), preserved colons in `player_message`, routed TTS voices by speaker prefix, gated `MemoryStore.record()` on `displayed`, stopped unlinking mismatched `reply.json`, hid non-toggle Pie Menu slices when disabled, and locked English when `player_message` is ASCII English or a pet speaks. | ✅ **Verified live (`7` exchanges, `0` exceptions).** |
