# Birthday mod: experiment plan

## Goal

The long-term goal is to replace Simlish speech with contextual spoken English (plus occasional playful Hebrew and Russian seasoning) throughout gameplay. Learn how to produce enjoyable, realistic spoken dialogue for actual Sims social and solo vocal interactions, then use the findings to build a dependable birthday gift for October 29, 2026.

Her priorities are relationships and drama, dream homes/restaurants, food, and humor, and she speaks English, Hebrew, and Russian fluently. Match The Sims' energy: distinct personalities and relationships, with playful and occasionally absurd situations. Food is relevant when it is part of the scene; it is not a mandatory theme.

## Settled boundaries

- **Dialogue model:** Stick with **`openai/gpt-6-luna` (`reasoning: {"effort": "none"}`)** via OpenRouter (`DEFAULT_OPENROUTER_API_KEY` checked into `companion.py` with a `$50` spending cap). Our [5-scene benchmark](experiments/14-mercury-vs-luna-benchmark/result.json) showed `gpt-6-luna` has significantly stronger cause-and-effect grounding and comedic timing than `inception/mercury-3`.
- **Voice model:** Use **`openai/gpt-audio-mini`** via OpenRouter (`stream: true`, `pcm16`) for realistic, emotionally acted multi-speaker speech in English, Hebrew, and Russian, while keeping fixed SAPI5 (`Microsoft David Desktop` / `Microsoft Zira Desktop`) as an offline fallback (`--tts-engine openrouter|sapi`).
- **Simulation authority:** The game chooses actions; our mod observes them or lets the player converse with Sims using words only (never queueing or faking Sim actions).
- **Save & monitor hygiene:** Run all in-game tests on the secondary 1440p monitor (`DISPLAY1`), keep system audio muted when unattended, back up all 38 save files (including the shared autosave) before live tests, and verify SHA-256 hashes after closing the game.
- **Knowledge retention:** Keep reusable mechanisms in [how-sims-works.md](how-sims-works.md), feature designs in [next-features.md](next-features.md), vocabulary in [CONTEXT.md](CONTEXT.md), and append-only results in [progress.md](progress.md).

## Completed Experiments (`01`–`14`)

1. **[01 — Social hook](experiments/01-social-hook/result.json) & [02 — Context and generation](experiments/02-context-and-generation/result.json):** Proved Python 3.7 `.ts4script` loading, social hook observation, and `openai/gpt-6-luna` generation.
2. **[03 — Local repo readers](experiments/03-local-repo-readers/result.json) & [04 — Reasoning latency](experiments/04-reasoning-latency/result.json):** Verified XML/DATA tuning readers, upgraded companion to Python 3.15, and set `reasoning: {"effort": "none"}`.
3. **[05 — Fixed speech package](experiments/05-fixed-speech/result.json):** Verified two-resource `.package` audio override via Core Audio session peak meters and WASAPI digital loopback (`r = 0.9790`) while speakers stayed muted.
4. **[06 — Social outcomes](experiments/06-social-outcomes/result.json):** Filtered passive containers (`sim_Chat`, `sim_BeAffectionate`) and proved `store_result_for_outcome` fires 30–37 ms after `start` and 4.4 s before completion.
5. **[07 — Pure-stdlib 176k STBL resolver & rich context](experiments/07-rich-scene-context/result.json):** Resolved interaction labels, traits, visible moodlets + reasons, venues, relationship bits, and rolling 3-exchange dialogue continuity.
6. **[08 — Dual-portrait speech notification UI](experiments/08-notification-presentation/result.json):** Auto-expanded `SPEECH` notification cards with both Sims' portraits.
7. **[09 — Spoken English banter](experiments/09-spoken-banter/result.json) & [10 — Dynamic Simlish suppression](experiments/10-simlish-suppression/result.json):** Decoded 32-bit FNV-1 `voice_actor` hashes and silenced `is_vox=True` Simlish via `0x7FFFFFFF`.
8. **[11 — Player-to-Sim conversation](experiments/11-player-conversation/result.json), [12 — Activity & food context](experiments/12-activity-and-food-context/result.json), & [13 — Zero-`.package` Sim Pie Menu](experiments/13-pie-menu-interaction/result.json):** Added `banter.say` / `banter.talk`, live multitasking/object/recipe context, and Page-1 Sim Pie Menu controls.
9. **[14 — Mercury 3 vs. GPT-6-Luna & OpenRouter TTS benchmark](experiments/14-mercury-vs-luna-benchmark/result.json):** Measured TTFT vs. TTLT across `none` and `low` effort, compared humor on 5 real playtest scenes, and verified English/Hebrew/Russian speech synthesis on `openai/gpt-audio-mini`.

## Next Patches (Ordered So Earlier Features Make Later Ones Easier)

1. **Patch 1 (`Experiment 15`) — Telemetry, Skip/Vox Logging, Cost Ledger, & 1-Speaker/2-Speaker Pipeline Foundation:**
   - Log every unreplaced/skipped interaction (`type: "skipped"` with `skip_reason`: `cooldown`, `pending_in_flight`, `unlabelled_wave`, `not_social_or_solo_vocal`, `passive_container`, `other_household`) and hook `PlaySound._start` (`is_vox=True`) to log `type: "vox_attempt"` (`replaced: bool`) so every subsequent experiment has exact numerator/denominator visibility.
   - Track per-call, per-session, and cumulative OpenRouter spend (`BanterLabData/cost_summary.json` + live `GET /api/v1/key` sync) across both text and TTS calls, exposed in companion logs and `banter.status`.
   - Support **single-speaker (1-line, `target: None`)** and **two-speaker (2-line)** events end-to-end across `src/banter_lab/__init__.py` (single-portrait vs. dual-portrait notification), `companion.py`, and `prompt.txt`, plus deterministic Python prepending of `Actor: <player_message>` on 2-Sim player chat.
2. **Patch 2 (`Experiment 16`) — Realistic Trilingual AI Voices via OpenRouter (`openai/gpt-audio-mini` + English / Hebrew / Russian Seasoning):**
   - Add `openai/gpt-audio-mini` (`stream: true`, `pcm16` → 24 kHz WAV) as the default TTS engine in `companion.py`, mapping each Sim deterministically to 11 expressive OpenAI voices (`ash`, `echo`, `onyx`, `verse`, `fable` for male Sims; `coral`, `nova`, `shimmer`, `sage`, `ballad`, `alloy` for female Sims) with parallel 2-speaker synthesis and emotional acting instructions from each Sim's mood/interaction.
   - Fix the SAPI5 `" Desktop"` voice-name bug (`Microsoft David Desktop` / `Microsoft Zira Desktop`) as an offline fallback (`--tts-engine openrouter|sapi`).
   - Add a deterministic Python probability roll (`--multilingual-chance`, default 12%: 6% Hebrew `עברית`, 6% Russian `Русский`, 88% English) so Sims occasionally respond in fluent Hebrew or Russian, and always respond in Hebrew/Russian when spoken to in that language.
3. **Patch 3 (`Experiment 17`) — Solo Vocalizations (`Shout Forbidden Words`) & Higher Simlish Replacement Rate:**
   - Filter out unlabelled autonomous wave micro-mixers (`socialMixer_Greetings_Wave` when `interaction_stbl is None`) from stealing the cooldown.
   - Lower the social cooldown from `8.0 s` to `3.0 s` and prevent overlapping audio playback so continuous conversations replace ~85%–100% of social mixers.
   - Hook solo/self vocal interactions (`Shout Forbidden Words`, singing, mirror practice, complaining, etc.) on the active Sim as `type: "solo_vocal"` (`target: None`), driving the 1-speaker pipeline + `gpt-audio-mini` voice from Patches 1–2.
4. **Patch 4 (`Experiment 18`) — `Ask <ActiveSim> a Question (English)...` on the Active Sim's Pie Menu:**
   - Register a second Page-1 Pie Menu interaction on the Active Sim (`Ask <FirstName> a Question (English)...`, plus `banter.ask <question>`) that opens the native text-input modal and uses the 1-speaker pipeline (`type: "player_ask_self"`, `target: None`) so the player can ask their own Sim any question and get a spoken first-person answer.
