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

`src/banter_lab` observes social interactions involving the active household and supports direct player-to-Sim conversation. Click your active Sim for **Enable/Disable English Banter** and **Ask <Sim> a Question (English)...**; click another Sim for **Speak to <Sim> (English)...**. On lot load it starts `companion.py` from this repository with `--parent-pid`, so no terminal is needed.

Console commands (`Ctrl+Shift+C`):

| Command | Effect |
| --- | --- |
| `banter.ai` / `banter.stop` | Turn English banter on / off (same as the pie menu). |
| `banter.talk <first> <last>` | Open the text box to speak as your active Sim to a Sim on this lot. |
| `banter.ask [question]` | Ask your active Sim a question (no question opens the text box). |
| `banter.mute on` / `off` | Silence or restore Simlish `voice_actor` (`0x7FFFFFFF`). |
| `banter.status` | Print state, skip counts, and cost; log a full snapshot to `events.jsonl`. |
| `banter.logs [on|off|tail]` | Mirror companion log lines into the console. |
| `banter.reload` | Hot-reload `BanterLab.ts4script`. |

Experiment-only commands (`banter.start`, `trace`, `test`, `audio`, `summon`, `say`, `solo`, `menu`) were removed on 2026-10-22; their results live in `experiments/` and git history.

Build using Python 3.7, matching the installed game:

```powershell
& '.\.local\python37\python.exe' '.\build.py'
```

The build writes `dist/BanterLab.ts4script` and `dist/BanterLabUI.package` and deploys both to `C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab`. Logs and `reply.json` live in its `BanterLabData` child directory. Rebuild after any game update: `BanterLabUI.package` ships patched copies of `Notifications.gfx` and `Dialog.gfx`.

## Generation companion (`companion.py`)

Python 3.15, standard library only. The game starts it; it exits when the game exits, and a lock file (`.local/companion.lock`) keeps a single instance.

- Tails `events.jsonl`, calls `openai/gpt-6-luna` (`reasoning: none`) through OpenRouter, and writes `reply.json`.
- Resolves interaction, trait, buff, venue, and relationship names from the game's string tables (`.local/stbl_en_us.json` cache).
- Synthesizes each line with `openai/gpt-audio-mini` in parallel. A line the audio model refuses or doesn't read verbatim stays silent; the text still shows.
- Plays the WAV when the game logs `displayed`.
- Cost: the session cost is the sum of per-call `usage.cost`; the total is the dedicated key's usage on OpenRouter (`cost_summary.json`).

Generate text for one captured event (offline prompt experiments, no audio):

```powershell
python3.15 '.\companion.py' --once '.\.local\scene.json'
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

## Experiments 14–16: Cost Tracking, OpenRouter Neural TTS (`gpt-audio-mini`), Trilingual Seasoning, Solo Vocalizations (`Shout Forbidden Words`), & `Ask <Sim> a Question`

- **Checked-in project API key & cost ledger ([companion.py](companion.py)):**
  - Uses `DEFAULT_OPENROUTER_API_KEY` (`$50` cap) by default and maintains `BanterLabData/cost_summary.json` (session + cumulative spend across text and TTS calls, synced with `GET https://openrouter.ai/api/v1/key`).
- **Realistic trilingual AI voices (`openai/gpt-audio-mini`):**
  - Default `--tts-engine openrouter` streams 24 kHz neural audio for each Sim using 11 distinct OpenAI voices (`ash`, `echo`, `onyx`, `verse`, `fable` for male Sims; `coral`, `nova`, `shimmer`, `sage`, `ballad`, `alloy` for female Sims) with parallel 2-speaker synthesis, mood-based delivery tone, and a refusal guard that falls back to fixed Desktop SAPI5 (`Microsoft David Desktop` / `Microsoft Zira Desktop`).
  - `--multilingual-chance 0.12` rolls a deterministic Python probability (88% English, 6% Hebrew `עברית`, 6% Russian `Русский`) and automatically matches Hebrew or Russian when the player types in that language.
- **Solo vocalizations (`Shout Forbidden Words`, etc.) & higher Simlish replacement rate:**
  - Filters out unlabelled autonomous wave micro-mixers (`socialMixer_Greetings_Wave`), lowers the social cooldown from `8.0 s` to `3.0 s`, logs every skipped interaction (`type: "skipped"`) and `PlaySound(..., is_vox=True)` call (`type: "vox_attempt"`), and captures 1-Sim vocal actions (`type: "solo_vocal"`).
- **Two Page-1 Pie Menu controls on your Active Sim:**
  - Clicking your **Active Sim** shows both **`Enable/Disable English Banter`** and **`Ask <FirstName> a Question (English)...`** (or `banter.ask <question>` in the console).
  - Clicking **any other Sim** shows **`Speak to <FirstName> (English)...`**.
  - Added `banter.solo` and `banter.reload` (in-place hot reload of `BanterLab.ts4script`).
