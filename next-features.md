# 🚀 Next Features & Architecture Plan (Pre-Implementation)

This document captures findings from your first live playtest at the Karaoke Bar and Residential lot (`events.jsonl` events `1`–`31`), diagnoses the two issues you spotted (`Shout Forbidden Words` and identical TTS voices), records our live latency/humor/multilingual-TTS benchmarks ([14-mercury-vs-luna-benchmark/result.json](experiments/14-mercury-vs-luna-benchmark/result.json)), and lays out the design for the next batch of experiments before we implement them.

---

## 1. Richer Telemetry: Logging Every Unreplaced Simlish Attempt 📋🔍

Right now, `_observe` in [src/banter_lab/__init__.py](src/banter_lab/__init__.py) silently returns early whenever an interaction is filtered out or throttled, which made it impossible to see from `events.jsonl` alone what percentage of Simlish was skipped while `banter.mute on` was active.

### Planned Logging & Debugging Upgrades
1. **Log every skipped interaction (`type: "skipped"`):** Whenever an interaction involving the active household (or a configurable lot-wide debug flag) is *not* turned into English banter, write a compact record to `events.jsonl` with the exact reason:
   - `skip_reason`: `"not_social_or_solo_vocal"` | `"passive_container"` | `"unlabelled_wave"` | `"pending_in_flight"` | `"cooldown"` | `"other_household"`
   - `interaction`, `interaction_stbl`, `is_social`, `is_super`, `actor_name`, `target_name`
   - `cooldown_remaining_s` and `pending_event_id` (when throttled)
2. **Hook `PlaySound._start` for `is_vox=True` (`type: "vox_attempt"`):** Log whenever the engine attempts to play a Simlish voice cue (`sound_id`, `sim_name`, `is_muted`, `active_interaction`, and whether an English banter event covered that Sim within the last `N` seconds). That gives us an exact **replaced vs. unreplaced Simlish ratio** after every playtest.
3. **End-of-session / live `banter.status` summary:** Report counts of `generated`, `displayed`, `skipped_by_reason`, and session/total `$` cost right in the companion console and `banter.status`.

---

## 2. TTFT vs. TTLT & `inception/mercury-3` (`none` vs. `low`) Benchmark ⚡

### Why TTLT Matters (and Why Diffusion LLMs Behave Differently)
- **TTLT (Time To Last Token)** is what governs our latency whenever we wait for the full text response before synthesizing audio and displaying the notification popup.
- Because `inception/mercury-3` is a **diffusion language model** rather than an autoregressive transformer, once any internal reasoning finishes, it denoises the entire visible output in a single **`15–38 ms` burst** (`TTFT_content ≈ TTLT`).
- By contrast, `openai/gpt-6-luna` streams tokens sequentially over `~400–600 ms` after `TTFT_content`.

### Live 5-Scene Benchmark (`none` vs. `low` on Your Real Gameplay Scenes)
We replayed 5 real scenes from your morning `events.jsonl` using the full 1,000-token scene context and `prompt.txt` ([full JSON results](experiments/14-mercury-vs-luna-benchmark/result.json)):

| Model & Effort | Median `TTFT_content` | Median `TTLT` | Min–Max `TTLT` | Reasoning Tokens Used | Avg Cost / Exchange | Behavior with `max_tokens=300` |
|---|---:|---:|---:|---:|---:|---|
| **`inception/mercury-3` (`effort="none"`)** | **`0.472 s`** | **`0.487 s`** | `0.338–0.979 s` | **`0`** | **`$0.000093`** | **100% complete** (`3.9×` faster TTLT than Luna!) |
| **`inception/mercury-3` (`effort="low"`, `max=300`)** | *(none on 4/5)* | `1.074 s` | `0.847–1.312 s` | `200–295` | `$0.000151` | **4 out of 5 failed** (burned all 300 tokens on reasoning and emitted **0 content tokens**!) |
| **`inception/mercury-3` (`effort="low"`, `max=1000`)** | `1.226 s` | `1.336 s` | `0.884–2.236 s` | `181–838` | `$0.000228` | Complete, but **`2.7×` slower** and **`2.5×` pricier** than `effort="none"` (and slower than Luna on 2/5 scenes). |
| **`openai/gpt-6-luna` (`effort="none"`)** | `1.390 s` | **`1.902 s`** | `1.844–1.969 s` | **`0`** | `$0.000111` | **100% complete**, rock-solid `1.84–1.97 s` TTLT. |

**Takeaway on `none` vs. `low`:**
- **`effort="low"` is NOT faster than `effort="none"`**—our earlier single-call `0.480 s` result happened only because `max_tokens: 120` cut the model off mid-sentence after `106` reasoning tokens + `9` content tokens!
- When allowed to finish (`max_tokens: 1000`), `mercury-3 (effort="low")` spends `181–838` tokens thinking (`1.34 s` median TTLT, up to `2.24 s`).
- **`effort="none"` is the clear speed winner** (`0.487 s` median TTLT, `0` reasoning tokens).

---

## 3. Humor & Intelligence Benchmark: `gpt-6-luna` vs. `mercury-3` 🎭😂

Here is how all three configurations performed side-by-side on 5 real scenes from your morning session:

### Scene A — Player says `"I like your butt"` to Mary Greenburg (`ELDER`, at Karaoke Bar)
- **`gpt-6-luna (none)` (`1.84 s`):**
  > **Alex Keen:** I like your butt.
  > **Mary Greenburg:** Well! That’s a bold thing to say to a woman at karaoke. Thanks, I think.
- **`mercury-3 (none)` (`0.39 s`):**
  > **Alex Keen:** I like your butt.
  > **Mary Greenburg:** At my age? Well, at least it still works. *(Used Mary's `ELDER` age field for a great punchline!)*
- **`mercury-3 (low)` (`1.34 s`):**
  > **Alex Keen:** I like your butt.
  > **Mary Greenburg:** Well, that’s… a first. You’re about my grandson’s age, dear.

### Scene B — `Wait For Drink` at Karaoke Bar (`Alex Keen` Sobering Up → `Anaya Jang` with `"Flaming"` drink buff & `"Righteous Riffs"` guitar buff)
- **`gpt-6-luna (none)` (`1.97 s`):**
  > **Alex Keen:** Finally, a drink. I was beginning to feel suspiciously responsible.
  > **Anaya Jang:** Careful—this one’s literally blazing. Your confidence may need a fire extinguisher. *(Wove together `Wait For Drink`, `Sobering Up`, `Flaming`, and `Confident`!)*
- **`mercury-3 (none)` (`0.53 s`):**
  > **Alex Keen:** You look like you’ve been waiting for that drink longer than I have. Want me to flag the bartender?
  > **Anaya Jang:** Smooth move. But I’m fine — I’m more caught up in that guitarist anyway.
- **`mercury-3 (low)` (`1.23 s`):**
  > **Alex:** Two drinks, coming right up. You're looking cozy over there.
  > **Anaya:** It's the sofa—and the songs. Wait's worth it.

### Scene C — `Throw Drink` (`Casey Gary` Angry throws a drink at `Alex Keen` Confident)
- **`gpt-6-luna (none)` (`1.90 s`):**
  > **Casey Gary:** There. Now the karaoke machine isn’t the only thing making a scene.
  > **Alex Keen:** You threw a drink at me and still missed the beat. Impressive, honestly. *(Nailed the physical action and who threw the drink at whom.)*
- **`mercury-3 (none)` (`0.34 s`):**
  > **Casey Gary:** You think you're so smooth up there, huh?
  > **Alex Keen:** Wow, okay. You got me. Real smooth move. *(Missed mentioning the thrown drink.)*
- **`mercury-3 (low)` (`2.24 s`, `705` reasoning tokens):**
  > **Casey:** "That's for the karaoke comment! I don't even know what it was, but I'm still mad!"
  > **Alex:** "Brava. You look like a wet cat now—and I mean that fondly." *(Got the direction backwards—Casey threw the drink at Alex, yet Alex says Casey looks like a wet cat!)*

### Scene D — `Discuss Color Theory` (`Anaya` Uncomfortable with `"Cramping"` watching Sports on TV; `Alex` Neat eating `"Ham and Cheese Sandwich"`)
- **`gpt-6-luna (none)` (`1.95 s`):**
  > **Anaya Jang:** Those colors on the screen are fighting. The blue’s winning, though.
  > **Alex Keen:** I thought you meant the teams. Either way, blue’s got my sandwich’s vote.
- **`mercury-3 (none)` (`0.49 s`):**
  > **Anaya Jang:** So the couch is more of a burnt sienna, don't you think? Really grounds the whole... oof.
  > **Alex Keen:** I was just counting the crumbs on my sandwich. But sure, sienna. You okay? *(Great grounded exchange—caught the cramping `"oof"` and Neat sandwich-crumb counting!)*
- **`mercury-3 (low)` (`2.19 s`, `838` reasoning tokens):**
  > **Anaya:** "That ad's using split-complementary colors. Sorry, cramps make me babble about art."
  > **Alex:** "It's working. You've got a good eye. Want half my sandwich?"

### Scene E — Player asks `"How do you feel?"` (`Alex` in Shower; `Anaya` Flirty on loveseat watching `"Watch PolitiSim"`)
- **`gpt-6-luna (none)` (`1.86 s`):**
  > **Alex Keen:** How do you feel?
  > **Anaya Jang:** Flirty, despite that political broadcast. You look bored enough to be an interesting distraction. *(Followed the verbatim `player_message` rule on Line 1.)*
- **`mercury-3 (none)` (`0.98 s`):**
  > **Alex Keen:** Depends. Showering with you is better than that sad meal I choked down.
  > **Anaya Jang:** I feel like making something beautiful. Wanna be my muse? *(Violated the prompt rule that Line 1 must echo `player_message` verbatim, and hallucinated showering together!)*
- **`mercury-3 (low)` (`0.88 s`):**
  > **Alex Keen:** How do you feel?
  > **Anaya Jang:** Better now that you're out of the shower—though this TV host keeps yapping about zoning laws.

### Verdict on Humor & Intelligence (`Luna` vs. `Mercury 3`)
1. **Why Luna is noticeably smarter on complex scenes:** `gpt-6-luna` consistently understands *who did what to whom* (`Throw Drink`), connects witty details across buffs/objects (`Flaming` drink + `Confident`, `Sports` teams + `Color Theory` + `Sandwich`), and strictly obeys formatting constraints.
2. **Where `mercury-3 (effort="none")` shines:** At `0.34–0.53 s` TTLT, it is almost **4× faster** than Luna and still writes punchy conversational banter (`At my age? Well, at least it still works`, `counting the crumbs on my sandwich`), but it needs **tighter prompt scaffolding**:
   - For `player_message`, **we should not ask the LLM to echo Line 1 at all**—`companion.py` should prepend `Alex Keen: <player_message>` deterministically in Python and ask the LLM *only* for the target Sim's 1-line reply!
   - Make `interaction_label` (`"Casey Gary just performed 'Throw Drink' on Alex Keen (outcome: SUCCESS)"`) an explicit top-level sentence in the user prompt rather than a raw JSON key so `mercury-3 (none)` never misses the physical action.
3. We can support `--model inception/mercury-3` and `--model openai/gpt-6-luna` (or use `mercury-3` for fast autonomous banter and `gpt-6-luna` when you want maximum wit).

---

## 4. OpenRouter TTS (`openai/gpt-audio-mini` vs. `Gemini 3.8 Flash`) + English / Hebrew / Russian Seasoning 🎙️🌍

### Why `openai/gpt-audio-mini` Wins on OpenRouter
1. **We tested `google/gemini-3.8-flash` for audio output on OpenRouter:**
   - In OpenRouter's `/api/v1/models` catalog, every `google/gemini-*` model (including `google/gemini-3.8-flash`) lists `audio` under **`input_modalities` only** (`output_modalities: ["text"]`).
   - Sending `modalities: ["text", "audio"]` to `google/gemini-3.8-flash` on OpenRouter returns **`HTTP 404: No endpoints found that support the requested output modalities: text, audio`**.
2. **`openai/gpt-audio-mini` works natively on our checked-in OpenRouter key—including fluent English, Hebrew, and Russian!**
   - Even better: your multilingual idea (**English + Hebrew + Russian**) immediately rules out simple local models like `Kokoro-82M` (whose phonemizer does not support Hebrew or Russian!).
   - We tested `openai/gpt-audio-mini` live on OpenRouter with dramatic Sims lines in **English**, **Hebrew**, and **Russian**:

| Language | Voice Tested | Sample Line | Measured `TTFA` | Measured `TTLT` | Audio Duration | Cost | Verbatim Transcript Check |
|---|---|---|---:|---:|---:|---:|---|
| **English** | `coral` | *"Your confidence is getting on my nerves. There—now we're both wearing the evening."* | `1.587 s` | `2.286 s` | `5.50 s` | `$0.000372` | ✅ 100% verbatim |
| **Hebrew (עברית)** | `shimmer` | *"אני רק מנסה לשתות קפה בשקט, למה כולם פה כל כך דרמטיים?"* | `1.439 s` | `2.077 s` | `4.55 s` | `$0.000340` | ✅ 100% verbatim |
| **Russian (Русский)** | `ash` | *"Я просто хотел спокойно съесть свой бутерброд, а тут опять драма!"* | `0.931 s` | `1.451 s` | `4.60 s` | `$0.000334` | ✅ 100% verbatim |

### How We'll Map Voices & Multilingual Seasoning
1. **11 distinct OpenAI voices mapped deterministically per Sim:**
   - Female Sims (`fa`, `fb`, `fc`, `fd` + `sim_id` hash): `coral`, `nova`, `shimmer`, `sage`, `ballad`, `alloy`
   - Male Sims (`ma`, `mb`, `mc` + `sim_id` hash): `ash`, `echo`, `onyx`, `verse`, `fable`
   - Parallel synthesis: For a 2-Sim exchange, `companion.py` requests Speaker 1 and Speaker 2 from `openai/gpt-audio-mini` **in parallel** (and can play Speaker 1 as soon as Speaker 1 finishes while Speaker 2 is still downloading!).
2. **Trilingual Easter Egg (English / Hebrew / Russian):**
   - Instead of asking the LLM to "pick a language 5% of the time" (LLMs are notoriously bad at random probabilities—they either do it 0% or 50% of the time!), **`companion.py` will roll a true Python `random.random()`**:
     - **~88% of autonomous socials:** `language: "English"`
     - **~6% of autonomous socials:** `language: "Hebrew (עברית)"`
     - **~6% of autonomous socials:** `language: "Russian (Русский)"`
     - **Player-initiated chat:** Replies in whatever language the player typed (with the same small chance of an NPC playfully slipping in a Hebrew or Russian expression!).

---

## 5. Why `"Shout Forbidden Words"` Made No Sound or Text 🤬🔇

In your screenshot, you clicked your Sim/floor and chose **Shout Forbidden Words** (`STBL 0xEF3E953A`, from *Parenthood* GP05). Nothing happened because:
1. `_social_participants(interaction)` in [src/banter_lab/__init__.py](src/banter_lab/__init__.py) currently requires `interaction.is_social == True` and `target != actor`. Clicking your own Sim runs the **solo** `SuperInteraction` (`target == actor` / `None`), so our hook returned early.
2. Meanwhile, `banter.mute on` (`voice_actor = 0x7FFFFFFF`) silenced the built-in Simlish swearing audio.
- **Planned fix:** Hook solo vocal interactions (`Shout Forbidden Words`, singing, mirror practice, complaining) as `type: "solo_vocal"` (`actor` only, `target = None`) and generate a 1-line outburst + single-portrait popup + 1-speaker `gpt-audio-mini` clip.

---

## 6. Raising the Simlish-to-English Replacement Rate 📊

In your morning session (`31` exchanges), active-Sim 2-person socials had a **~35%–50% replacement rate** because of:
1. The **8-second hard cooldown** (`if now - _last_shown < 8: return`) vs. Sims firing a mixer every `3.5–5.0 s`.
2. **`socialMixer_Greetings_Wave` spam** (`10` of your `31` events were unlabelled waves that ate the 8-second cooldown right before real conversation mixers!).
3. **0%** coverage of solo vocalizations (`Shout Forbidden Words`).

**Planned fix:** Filter out `socialMixer_Greetings_Wave` from triggering/consuming cooldowns, lower the cooldown to `3.0 s` (and prevent overlapping audio playback), and add `solo_vocal` coverage—while logging every skipped interaction (`type: "skipped"`) so we can measure the new replacement percentage directly.

---

## 7. Asking Your Own Sim a Question in English 🙋‍♂️💬

- **Click your Active Sim → `Ask <FirstName> a Question (English)...`:** Opens the in-game text box where **you (the player)** ask `<ActiveSim>` a question directly; `<ActiveSim>` answers in the first person (`1` line + `1` voice) grounded in their moodlets, traits, current activity/food, and surroundings.
- **Click another Sim → `Speak to <FirstName> (English)...`:** `<ActiveSim>` says your message to `<TargetSim>` (Line 1 prepended deterministically in Python) and `<TargetSim>` replies (`2` lines).

---

## 8. Session & Cumulative Cost Tracking 💰

- **Checked-in key:** `DEFAULT_OPENROUTER_API_KEY` (`sk-or-v1-9f579...d7d`, `$50` cap) is active in [companion.py](companion.py).
- **Cost tracker:** Record every text LLM call and every `openai/gpt-audio-mini` TTS call in `BanterLabData/cost_summary.json` (`session_cost_usd`, `total_cost_usd`, breakdown by `chat` vs. `tts`) and cross-check against `GET https://openrouter.ai/api/v1/key`.

---

## 9. Deferred / Future Horizon 🌅

- **Simultaneous background NPC chatter in English:** Once foreground Simlish replacement and voice synthesis are dialed in, allow background NPC-to-NPC conversations at venues (like the Karaoke Bar) to generate lower-volume/attenuated English background chatter without stealing foreground notification popups.
