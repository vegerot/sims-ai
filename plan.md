# BanterLab: plan

## Goal

Replace Simlish with contextual spoken English (plus occasional playful Hebrew and Russian) during M's real play. The birthday gift shipped on October 29, 2026; she plays with it installed, so the work now is making her evenings funnier and less repetitive, measured on her own events and ratings.

Her priorities are relationships and drama, dream homes/restaurants, food, and humor. Match The Sims' energy: distinct personalities and relationships, playful and occasionally absurd. Food matters when it is in the scene, not as a mandatory theme.

## Settled decisions (with the evidence)

- **Text model:** `x-ai/grok-4.20`, `reasoning: {"effort": "none"}`, for every scene. Fastest (0.83 s p50 on her 31 frozen scenes), explicit when `spicy`, and M's favorite in the blind ratings so far ([31](experiments/31-variety-spice-model-and-voice-bakeoff/result.json)). Rejected: Grok 4.7 (reasoning can't be disabled; 18× slower) and Grok 4.3 (half as explicit in sex scenes) ([32](experiments/32-grok-4.7-voice-moods-and-repeats/result.json)). Tentative until she finishes the Lines tab.
- **Voice:** `fish-audio/drama-3`, one fixed Fish library voice per Sim, the Sim's mood as a `[bracket]` direction (mood-specific for Sex and Happy, generic for Fine; [32](experiments/32-grok-4.7-voice-moods-and-repeats/result.json)). Pets speak through the deadpan Windows SAPI5 voices (Zira / David) as a collar translator.
- **Spice:** explicit lines only for adult humans in a sexual, romantic, nude, or intoxicated moment (`is_spicy`). WickedWhims scenes are voiced on start, on each animation change (≥ 25 s apart), and once at climax.
- **Simlish:** mute only the Sims whose line is replaced, and only until the English audio ends (`_mute_replaced`, `_audio_until`).
- **Simulation authority:** the game chooses actions; the mod observes them or lets the player talk with words only.
- **Verification rule:** a behavior is verified only when it shows up in the real game's `events.jsonl` (or a screenshot of the real game). Harness runs are labelled as harness runs.
- **Experiments before shipping:** a prompt or model change ships after a replay of her real captured events (`lab.py exp32 replay`, `lab.py exp31 text`) beats production on the measure that motivated it.
- **Live-test hygiene:** back up `saves/` before a live test and restore it afterwards (verify hashes); never touch `saves/WickedWhimsMod` or `saves/BasementalDrugs`. The mod stays installed: it's hers now.
- **Knowledge:** mechanisms in [how-sims-works.md](how-sims-works.md), vocabulary in [CONTEXT.md](CONTEXT.md), append-only results in [progress.md](progress.md), one `result.json` per experiment ([index](README.md#verified-experiments)).

## Open questions

1. **Text model:** does Grok 4.20 stay on top once M finishes the blind Lines tab (`lab.py exp31 serve`, then `analyze ratings`)?
2. **Climax line:** never fired live; WickedWhims ended both test scenes without a CLIMAX animation long enough to poll. Confirm on her next full scene.
3. **Ratings:** the Pie Menu writes `rating` events, but nothing reads them yet. Once she has rated a few dozen lines, join them to replies by `event_id` (model, `prompt_sha`, language, event type) and look for a pattern before changing anything.
4. **Latency:** text and speech run one after the other (about 0.8 s + 0.9 s). Overlapping speech synthesis with text streaming is the next speed-up worth measuring.

The October planning interview and prior-art research are in [planning.md](planning.md); the full history is in [progress.md](progress.md).
