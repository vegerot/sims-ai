# The Sims 4 birthday experiments

A birthday gift for October 29, 2026: contextual English banter that matches The Sims' playful energy. This directory is an experiment workspace, not the final mod architecture.

[Conversation archive](../sims4-ai-birthday-mod-experiments.md) records the interview, implementation, observed results, and closing state.

- [Plan](plan.md): goal, decisions, experiment sequence, and completion criteria.
- [Progress](progress.md): append-only handoff; newest entries are last.
- [How The Sims works](how-sims-works.md): reusable findings, mechanisms, and evidence.
- [Glossary](CONTEXT.md): project vocabulary.
- [Early planning and prior art](planning.md): interview and external research notes.
- [Local Sims repositories](repo-research.md): source entry points, tested tuning readers, and follow-up experiments.

Resume by reading `plan.md`, then the newest `progress.md` entries. Check the working copy, installed mod, running game, and relevant logs against the handoff before continuing.

## In-game script mod (`src/banter_lab`)

`src/banter_lab` observes social interactions and major milestone moodlets (`Big Moment!` drama reactions) involving the active household, and supports direct player-to-Sim conversation and 1-click inner monologues. Click your active Sim for **Enable/Disable English Banter**, **Ask <Sim> a Question (English)...**, and **Hear <Sim>'s Thoughts (English)**; click any other Sim or pet for **Speak to <Sim> (English)...** and 1-click **Hear <Sim>'s Thoughts (English)**. On lot load it starts `companion.py` from this repository with `--parent-pid`, so no terminal is needed.

Console commands (`Ctrl+Shift+C`):

| Command | Effect |
| --- | --- |
| `banter.status` | Print state, skip counts, and cost; log a full snapshot to `events.jsonl`. |
| `banter.logs [on|off|tail]` | Mirror companion log lines into the console. |
| `banter.reload` | Hot-reload `BanterLab.ts4script`. |
| `banter.stop` | Turn English banter off and restore any muted Simlish voices. |

All player controls (**Enable/Disable English Banter**, **Ask <Sim> a Question (English)...**, **Speak to <Sim> (English)...**, and 1-click **Hear <Sim>'s Thoughts (English)**) live on Page 1 of the Sim Pie Menu. Redundant and experiment-only console commands were removed on 2026-10-22; their results live in `experiments/` and repository history.

Build and deploy using Python 3.7 (or uninstall / wipe playtest data for a clean slate):

```powershell
& '.\.local\python37\python.exe' '.\build.py'
python3.15 '.\build.py' --uninstall
python3.15 '.\build.py' --reset-data
```

The build writes `dist/BanterLab.ts4script` and `dist/BanterLabUI.package` and deploys both to `C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab`. Runtime logs (`events.jsonl`, `companion.stdout.log`), `memories.json`, `cost_summary.json`, and `reply.json` live in `.local/data` outside OneDrive so OneDrive is never polled or written at runtime. Rebuild after any game update: `BanterLabUI.package` ships a patched copy of `Notifications.gfx` (`ShowNextMessage` honors `notification.timeout_duration`).

## Generation companion (`companion.py`)

Python 3.15, standard library only. The game starts it; it exits when the game exits, and a lock file (`.local/companion.lock`) keeps a single instance.

- Tails `events.jsonl`, calls `openai/gpt-6-luna` (`reasoning: none`) through OpenRouter, and writes `reply.json`.
- Resolves interaction, trait, buff, venue, and relationship names from the game's string tables (`.local/stbl_en_us.json` cache).
- Synthesizes human lines with `openai/gpt-audio-mini` and pet lines (`species != "HUMAN"`) with the deadpan built-in Windows SAPI5 robot voice (`Microsoft Zira Desktop` / `Microsoft David Desktop` at 24 kHz PCM) in parallel. If `gpt-audio-mini` refuses a spicy line (`!_transcript_matches`), that line retries on `google/gemini-3.8-flash-lite-tts` via `/api/v1/audio/speech`.
- Plays the WAV when the game logs `displayed`.
- Cost: the session cost is the sum of per-call `usage.cost`; the total is the dedicated key's usage on OpenRouter (`cost_summary.json`).

Generate text for one captured event (offline prompt experiments, no audio):

```powershell
python3.15 '.\companion.py' --once '.\experiments\replay-set'
```

## Verified experiments

1. **[01 — Social hook](experiments/01-social-hook/):** Verified `_trigger_interaction_start_event` and in-game notifications in the disposable `Banter Lab` save.
2. **[02 — Context and generation](experiments/02-context-and-generation/result.json):** First end-to-end live generation round-trip ([screenshot](experiments/02-context-and-generation/in-game.jpg)).
3. **[03 — Local repo readers](experiments/03-local-repo-readers/result.json):** Read-only verification of XML and binary `DATA` combined-tuning decoders across installed packages.
4. **[04 — Reasoning latency](experiments/04-reasoning-latency/result.json):** Verified explicit `reasoning: {"effort": "none"}` under Python 3.15 (zero reasoning tokens).
5. **[05 — Fixed English speech package](experiments/05-fixed-speech/result.json):** Packaged a two-resource override for `vo_expr_greet_uncomfortable_45f_fa` (`0xAE9960DCFFD5C32E`) and verified digital rendering in-game via Windows Core Audio session peaks and WASAPI loopback capture (`r = 0.9790` envelope correlation, `|r| = 0.6462` 16 kHz waveform correlation across 38,034 samples) while system speakers remained muted ([console screenshot](experiments/05-fixed-speech/in-game-console.png)).
6. **[06 — Social outcomes & lifecycle timing](experiments/06-social-outcomes/result.json):** Verified `store_result_for_outcome`, `_trigger_interaction_complete_test_event`, and `cancel` in live gameplay; found that `store_result_for_outcome` fires 30–37 ms after `start` and several seconds before animation completion, and filtered passive `sim_Chat` / `sim_BeAffectionate` containers ([in-game screenshot](experiments/06-social-outcomes/in-game-outcome-banter.png)).
7. **[07 — Rich scene context & STBL resolver](experiments/07-rich-scene-context/result.json):** Built a pure-stdlib DBPF + RefPack + STBL resolver (176,266 strings) and verified live resolution of interaction labels, traits, visible buffs/reasons, venue types, relationship bits, Sim voice metadata, and direct `BanterLabData/reply.json` delivery.
8. **[08 — Dual-portrait auto-expanded speech UI](experiments/08-notification-presentation/result.json):** Verified `FORCE_EXPAND` + `SPEECH` visual type + dual `IconInfoData` portraits so banter automatically expands in the top-right corner showing both Sims' faces ([screenshot](experiments/08-notification-presentation/dual-portrait-speech-popup.png)).
9. **[09 — Companion per-Sim spoken banter](experiments/09-spoken-banter/result.json):** Verified dynamic two-voice SSML WAV synthesis mapped from each Sim's `gender`, `voice_actor`, and `voice_pitch`, synchronized to the game's `displayed` event.
10. **[10 — Dynamic per-Sim Simlish suppression](experiments/10-simlish-suppression/result.json):** Decoded `sim_info.voice_actor` FNV-32 suffix hashes (`ma`, `mb`, `fa`, `fd`, `cb`) and verified that `banter.mute on` (`voice_actor = 0x7FFFFFFF`) silences `is_vox=True` Simlish voice playback (`0.0415` peak -> `0.0040` ambient floor) while preserving original `voice_actor` metadata and restoring on `banter.mute off` / `banter.stop` ([console screenshot](experiments/10-simlish-suppression/in-game-vox-mute-console.png)).
11. **[11 — Direct player-to-Sim conversation](experiments/11-player-conversation/result.json):** Verified both `banter.say` and a native in-game `UiDialogTextInputOkCancel` modal (`banter.talk`), plus a warm persistent TTS worker that cut WAV synthesis latency to **33–135 ms** ([modal screenshot](experiments/11-player-conversation/in-game-talk-modal.png), [reply screenshot](experiments/11-player-conversation/in-game-talk-reply.png), [`banter.say` screenshot](experiments/11-player-conversation/in-game-player-say.png)).
12. **[12 — Multitasking activity, object, & food context](experiments/12-activity-and-food-context/result.json):** Verified live extraction and STBL resolution of `sim.si_state` activities, target object catalog names (`"Watch World Culture Network"` on `"Been There, Watched That TV"`, `"Sit"` on `"Squarely There Modern Loveseat"`), `posture_state.carry_targets`, and `crafting_component.get_recipe()` dish names.

13. **[13 — Zero-`.package` Sim Pie-Menu injection](experiments/13-pie-menu-interaction/result.json):** Subclassed a base-game `ImmediateSuperInteraction` (`13142`) at runtime with `pie_menu_priority = 30` and hooked `Zone.on_loading_screen_animation_finished` so clicking your active Sim shows **`Enable English Banter`** / **`Disable English Banter`** on Page 1 of the Pie Menu and clicking any other Sim shows **`Speak to <Name> (English)...`**—with zero `.package` files or console commands required ([Enable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-self.png), [Disable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-disable.png)).

14. **[14 — Mercury 3 vs. GPT-6-Luna & OpenRouter TTS benchmark](experiments/14-mercury-vs-luna-benchmark/result.json):** Measured TTFT vs. TTLT across `none` and `low` effort, compared humor on 5 real playtest scenes, and verified English/Hebrew/Russian speech synthesis on `openai/gpt-audio-mini`.
15. **[15 — Cost tracking & OpenRouter neural TTS](experiments/15-cost-and-openrouter-tts/result.json):** Verified `openai/gpt-audio-mini` streaming PCM16 TTS in-game (`1.26–1.46 s` parallel 2-speaker synthesis across 11 voices) and OpenRouter cost tracking (note: the Gemini TTS comparison in `result.json` hit the chat model `google/gemini-3.8-flash`, not `google/gemini-3.8-flash-tts`).
16. **[16 — Ask-Self Pie Menu & solo vocalizations](experiments/16-solo-vocal-and-ask-self/result.json):** Verified **`Ask <Sim> a Question (English)...`** live in-game (4 events in `events.jsonl`); note that `result.json`'s `solo_vocal` and `vox_attempt` metrics came from a local mock harness, not the game.

17. **[17 — Humanize tables A/B](experiments/17-humanize-tables-ab/result.json):** Compared the 389-line `humanize_*` lookup tables against STBL labels + filtered raw tuning names across 5 real events from her save (`Slot_00000002.save`), confirming `openai/gpt-6-luna` grounds jokes just as well without the lookup tables and enabling a `-55.1%` total codebase reduction (`4,049` → `1,816` lines).
18. **[18 — OpenRouter TTS endpoint benchmark](experiments/18-openrouter-tts-endpoint-benchmark/result.json):** Verified the Antigravity scratch WAVs via `google/gemini-3.8-flash` audio transcription, benchmarked 5 `/api/v1/audio/speech` models across English/spicy/Hebrew/Russian, and added a 14-line per-line refusal fallback to `google/gemini-3.8-flash-lite-tts`.
19. **[19 — Line length & rhythm A/B](experiments/19-line-length-and-rhythm-ab/result.json) & [Replay set](experiments/replay-set/):** Benchmarked `8–22` vs. `6–16` vs. `5–11` words/line across 6 real save events (`10.85 s` → `8.18 s` → `7.27 s` avg audio duration), fixed missing `same_household` on `scene['relationship']` (`meimei <-> Kenya Bower`), and restored UTF-8 stdout reconfiguration in `companion.py`.
20. **[20 — Cleaned-context 7-scene replay verification](experiments/20-cleaned-context-replay-verification/result.json):** Verified all 7 real save scenes in `experiments/replay-set/` after filtering street-stranger townies, `trait_Attraction_*` turn-on spam, and passive room/lot buffs and preserving trailing `sentimentBit_*` entries (`avg_prompt_tokens = 1,921`).
21. **[21 — Gossip, chef/quality, social events, 3-Sim bystander, & keep-alive/SAPI5 acceleration](experiments/21-gossip-chef-situations-bystander-and-keepalive/result.json):** Cut warm Windows SAPI5 pet synthesis from `0.83 s` to `10–38 ms` (`22–70×` faster), added thread-local keep-alive TLS pooling, and verified cross-partner `recent_gossip`, `cooked_by` + dish `quality`, active `social_events` + `outfit`, 3-Sim `bystander` chime-ins, and 1-click `Hear <Sim>'s Thoughts (English)` live across `Slot_00000003.save` (`aurora Hussain` & `Chánh Linh`) and `Slot_00000002.save` (`Kenya Bower`, `Hitomi Ishii`, & `meimei`).
22. **[22 — Per-line RMS loudness normalization (`-18.5 dBFS`), silence trimming, outdoor weather, & carried props](experiments/22-loudness-normalization-and-outdoor-carry-context/result.json):** Fixed a `9.3–14.7 dB` loudness swing between whisper-quiet `gpt-audio-mini` (`-35.9 dBFS`) and `System.Speech` SAPI5 (`-21.2 dBFS`) via pure-stdlib speech-gated RMS normalization + `-1.0 dBFS` `tanh` soft-knee limiting + `25/55 ms` silence trimming (verified live at `-19.8` and `-19.3 dBFS` in `thought-1793095981266-1` and `thought-1793096326402-2`), added `posture_state.carry_aspects`, `pregnancy_tracker`, outdoor-only `season_service`/`weather_service` (`SUMMER, Rain Heavy Warm`), `Translate <Pet>'s Thoughts`, player-priority batch drain, and build-time path assertions.
23. **[23 — Automatic Drama-Moment spoken reactions (`Big Moment!`), legacy-shim deletions, & bounded `events.jsonl`](experiments/23-drama-reaction-and-replay-set-regression/result.json):** Piggybacked `_check_drama_moment` onto the existing `_ReplyPoller.poll` alarm (zero new engine hooks) to speak unprompted 1-line reactions on major romance/career/cooking/disaster moodlets (verified live in `drama-1793098032406-1` on `Horrible Date`: *"aurora Hussain: That date was so terrible, even the mold feels sorry for me."* at `-19.1 dBFS` RMS), deleted `_record_skip` disk writes, deleted legacy `_SPECIES_NAMES`/`object_sim` shims, filtered passive WickedWhims tracker buffs, and capped `events.jsonl` at `<= 2 MB` on startup.
24. **[24 — Post-drama `Sim text`, Dream-Home `lot_value`/`lot_rooms`, & `solo::` private-thought isolation](experiments/24-sim-text-dream-home-value-and-memory-isolation/result.json):** Isolated private 1-click `inner_thought` monologues under `solo::<Thinker>` so mind-reads never leak into shared `pair_memory`/`recent_gossip`, added `lot_value` + `lot_rooms` (`beds / baths`), and verified automatic dual-portrait **`Text from <Partner> → <Sim>`** (`text-1793100635692-3`) live in-game on `Slot_00000003.save`.
25. **[25 — Build/Buy `Renovation reaction` (`New Decor!`), Rental `daily_rent`/`star_rating`, Restaurant `ordered` dishes, pipelined `player_chat` Line-1 TTS, & Lovestruck Turn-On/Turn-Off restoration](experiments/25-renovation-restaurant-and-pipelined-chat/result.json):** Promoted `drama_reaction` and `sim_text` to first-class event types (deleting the `is_sim_text` boolean flag and supporting off-lot `SimInfo` text senders), pre-started `player_chat` Line-1 TTS concurrently with 1-line Target LLM generation (`1.39–2.35 s` chat latency), restored Lovestruck non-color Turn-Ons/Turn-Offs + `Fear_BeingCheatedOn` + `VeryAttracted`/`RepelledBy` bits, added *Dine Out* `restaurant_order` + *For Rent* `daily_rent`/`owed_rent`/`star_rating`, and verified live in-game on `11C Sungai Point` (`chat-1793102247137-4` citing exact `§129 a day` rent, `renov-1793103246479-5` `AURORA HUSSAIN (NEW DECOR!)` reacting to exact `+§1,555` stove purchase, and `thought-1793104042587-6` isolated to `solo::Liên Sadya`).
26. **[26 — `ENG_US` Mod STBL locale filtering, `AspirationTrack.display_text` resolution, universal `_ReplyPoller` timeout recovery, & *WickedWhims*/*Basemental* drama triggers](experiments/26-english-mod-stbls-aspirations-and-mod-drama/result.json):** Filtered `STBL` `Instance64` high byte `(inst_hi >> 24) == 0` (`ENG_US`) + `meta v2` cache invalidation (preventing `68` foreign-locale overwrites across `11,974` English Mod STBL strings), resolved `AspirationTrack.display_text` (`"Track_Love_C"` → `"Paragon Partner"`), moved `_pending` timeout recovery into `_ReplyPoller.poll` for all event types, collapsed `_pie_*` globals into a single `_pie_classes` tuple, and verified cold-boot Page-1 Pie Menu + `aspiration_stbl` (`thought-1793110619002-1`) and live *WickedWhims* `Satisfying Encounter` `Big Moment!` drama reaction (`drama-1793111061913-2`) in-game on `Slot_00000003.save`.
