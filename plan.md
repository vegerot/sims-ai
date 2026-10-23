# Birthday mod: experiment plan

## Goal

The long-term goal is to replace Simlish speech with contextual spoken English (plus occasional playful Hebrew and Russian seasoning) throughout gameplay. Learn how to produce enjoyable, realistic spoken dialogue for actual Sims social and solo vocal interactions, then use the findings to build a dependable birthday gift for October 29, 2026.

Her priorities are relationships and drama, dream homes/restaurants, food, and humor, and she speaks English, Hebrew, and Russian fluently. Match The Sims' energy: distinct personalities and relationships, with playful and occasionally absurd situations. Food is relevant when it is part of the scene; it is not a mandatory theme.

## Settled boundaries

- **Dialogue model:** Stick with **`openai/gpt-6-luna` (`reasoning: {"effort": "none"}`)** via OpenRouter (`DEFAULT_OPENROUTER_API_KEY` checked into `companion.py` with a `$50` spending cap). Our [5-scene benchmark](experiments/14-mercury-vs-luna-benchmark/result.json) showed `gpt-6-luna` has significantly stronger cause-and-effect grounding and comedic timing than `inception/mercury-3`.
- **Voice model:** Use **`openai/gpt-audio-mini`** via OpenRouter (`stream: true`, `pcm16`) for emotionally acted multi-speaker speech in English, Hebrew, and Russian. Each line is synthesized independently in parallel; if a line is refused or its transcript fails the 60% word-overlap check (`_transcript_matches`), that line stays silent while the text notification still displays. (Desktop SAPI5 was removed in `3a4539bd342f` so robotic fallback voices never break immersion.)
- **Selective Simlish muting & one-exchange-at-a-time pacing (`b6780621ec27`):** Mute a Sim's `voice_actor` (`0x7FFFFFFF`) only inside `_submit()` when their line is being replaced by English, and restore their original `voice_actor` once the English WAV finishes playing (`audio_dur + 0.5 s`, or immediately on silent/error replies). Hold `_audio_until = now + audio_dur` in `_busy()` (`skip_reason: "audio_playing"`) so overlapping autonomous socials play their natural Simlish without cutting off active `winsound.PlaySound(..., SND_ASYNC)` English audio.
- **Verification rule (`6081c3de6550`):** A behavior is **verified** only when it appears in the real game's `BanterLabData/events.jsonl` (or a screenshot/recording of the real game). Offline or mock-harness runs must be labelled as harness runs.
- **Simulation authority:** The game chooses actions; our mod observes them or lets the player converse with Sims using words only (never queueing or faking Sim actions).
- **Save & monitor hygiene:** Run all in-game tests on the secondary 1440p monitor (`DISPLAY1`), keep system audio muted when unattended, back up all 40 files in `saves/` (including `Slot_ffffffff.save`) before live tests, and verify SHA-256 hashes after closing the game.
- **Knowledge retention:** Keep reusable mechanisms in [how-sims-works.md](how-sims-works.md), vocabulary in [CONTEXT.md](CONTEXT.md), and append-only results in [progress.md](progress.md).

## Completed Experiments (`01`–`16`) & Real-Save Verification

1. **[01 — Social hook](experiments/01-social-hook/result.json) & [02 — Context and generation](experiments/02-context-and-generation/result.json):** Proved Python 3.7 `.ts4script` loading, social hook observation, and `openai/gpt-6-luna` generation.
2. **[03 — Local repo readers](experiments/03-local-repo-readers/result.json) & [04 — Reasoning latency](experiments/04-reasoning-latency/result.json):** Verified XML/DATA tuning readers, upgraded companion to Python 3.15, and set `reasoning: {"effort": "none"}`.
3. **[05 — Fixed speech package](experiments/05-fixed-speech/result.json):** Verified two-resource `.package` audio override via Core Audio session peak meters and WASAPI digital loopback (`r = 0.9790`) while speakers stayed muted.
4. **[06 — Social outcomes](experiments/06-social-outcomes/result.json):** Filtered passive containers (`sim_Chat`, `sim_BeAffectionate`) and proved `store_result_for_outcome` fires 30–37 ms after `start` and 4.4 s before completion.
5. **[07 — Pure-stdlib 176k STBL resolver & rich context](experiments/07-rich-scene-context/result.json):** Resolved interaction labels, traits, visible moodlets + reasons, venues, relationship bits, and rolling dialogue continuity.
6. **[08 — Dual-portrait speech notification UI](experiments/08-notification-presentation/result.json):** Auto-expanded `SPEECH` notification cards with both Sims' portraits.
7. **[09 — Spoken English banter](experiments/09-spoken-banter/result.json) & [10 — Dynamic Simlish suppression](experiments/10-simlish-suppression/result.json):** Decoded 32-bit FNV-1 `voice_actor` hashes and silenced `is_vox=True` Simlish via `0x7FFFFFFF`.
8. **[11 — Player-to-Sim conversation](experiments/11-player-conversation/result.json), [12 — Activity & food context](experiments/12-activity-and-food-context/result.json), & [13 — Zero-`.package` Sim Pie Menu](experiments/13-pie-menu-interaction/result.json):** Added `banter.talk`, live multitasking/object/recipe context, and Page-1 Sim Pie Menu controls.
9. **[14 — Mercury 3 vs. GPT-6-Luna & OpenRouter TTS benchmark](experiments/14-mercury-vs-luna-benchmark/result.json):** Measured TTFT vs. TTLT across `none` and `low` effort, compared humor on 5 real playtest scenes, and verified English/Hebrew/Russian speech synthesis on `openai/gpt-audio-mini`.
10. **[15 — Cost tracking & OpenRouter neural TTS](experiments/15-cost-and-openrouter-tts/result.json) & [16 — Ask-Self Pie Menu](experiments/16-solo-vocal-and-ask-self/result.json):** Verified parallel 2-speaker `openai/gpt-audio-mini` synthesis and **`Ask <Sim> a Question (English)...`** live in-game; corrected harness-only and wrong-model records (`6081c3de6550`) and deleted experiment scaffolding, SAPI fallback, the broken `vox_attempt` meter, and heartbeat file churn (`3a4539bd342f`).
11. **Initial live verification on her save (`Kenya Bower` at `Boiling Point`, `2026-10-22`):** Verified `companion_spawned` (`--parent-pid` auto-launch and clean exit), `pie_menu_installed` (19 Sims), all save-aware context fields (`lot_name`, `lot_traits`, `careers`, `skills`, `extra_traits`, `aspiration`, `household_funds`, `social_connections`, `reverse_bits`), `_audio_until` overlap protection (`skip_reason: "audio_playing"`), and 7 voiced exchanges (`1792724276127-1`..`1792724945807-7`) with zero errors in `events.jsonl`.

## Remaining Playtest & Simplification Checklist (Handoff for Computer-Use Harness)

1. **Verify `BanterLabUI.package` patches in-game (`Dialog.gfx` & `Notifications.gfx`):**
   - Open `Speak to <Sim> (English)...` or `Ask Kenya a Question (English)...` via the Pie Menu (or `banter.ask`), type a message, and press `Enter` (`return`) without clicking the checkmark button to verify `Dialog.gfx`'s `Enter`-to-send patch logs `player_chat` / `player_ask_self` in `events.jsonl`.
   - Visually confirm that a speech notification card stays visible for `timeout_duration_ms` (`audio_duration + 2 s`) and then auto-dismisses (`Notifications.gfx` `readDuration` patch).
2. **Verify home-lot context (`3 Sequoia Cottage`), pet `breed` (`meimei`), and neighbor (`gefen berger`):**
   - `Slot_00000002.save` loads with Kenya Bower currently visiting `Boiling Point` (`venue_Restaurant`). Travel home with Kenya Bower to `3 Sequoia Cottage` (where her dog `meimei` and multi-unit neighbor `gefen berger` are instanced) and verify `species` / `breed` / `breed_stbl` and neighbor social interactions in `events.jsonl`.
3. **Verify selective Simlish muting (`_muted_until`) restoration across Sims:**
   - Confirm in-game that `_muted_until` mutes only the participating Sims during an active English exchange, leaves unreplaced Sims in natural Simlish, and restores the speaking Sims' original `voice_actor` hash `0.5 s` after the WAV finishes.
4. **Run the offline A/B context experiment (`companion.py --once`):**
   - Using the 7 real events captured from her save (`1792724276127-1`..`1792724945807-7` in `BanterLabData/events.jsonl`), compare the ~400 lines of `humanize_*` lookup tables in `companion.py` against raw tuning names + STBL labels, and delete any tables that do not measurably improve `openai/gpt-6-luna`'s output.
