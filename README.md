# The Sims 4 birthday experiments

A birthday gift for October 29, 2026: contextual English banter that matches The Sims' playful energy. This directory is an experiment workspace, not the final mod architecture.

[Conversation archive](../sims4-ai-birthday-mod-experiments.md) records the interview, implementation, observed results, and closing state.

- [Plan](plan.md): goal, decisions, experiment sequence, and completion criteria.
- [Progress](progress.md): append-only handoff; newest entries are last.
- [How The Sims works](how-sims-works.md): reusable findings, mechanisms, and evidence.
- [Glossary](CONTEXT.md): project vocabulary.
- [Early planning and prior art](planning.md): interview and external research notes.

Resume by reading `plan.md`, then the newest `progress.md` entries. Check the working copy, installed mod, running game, and relevant logs against the handoff before continuing.

## First experiment

`src/banter_lab` observes social interactions involving the active household. It is dormant until explicitly started in the game's cheat console (`Ctrl+Shift+C`):

| Command | Effect |
| --- | --- |
| `banter.test` | Show a manual English notification. |
| `banter.start` | Capture real scene context and show clearly labeled fixed test lines. |
| `banter.ai` | Request generated banter; start the companion first. |
| `banter.stop` | Stop observing and cancel reply polling. |
| `banter.status` | Print state and log active/nearby Sims for debugging. |
| `banter.summon Bella Goth` | Test-save setup: request that a named NPC enter the zone. This changes the test scene; it does not prove arrival. |

Build using Python 3.7, matching the installed game:

```powershell
& '.\.local\python37\python.exe' '.\build.py'
```

The archive is `dist/BanterLab.ts4script`. Local tools, generated archives, game-context logs, and private test artifacts are ignored. No model credential belongs in the script archive.

Restart the game after replacing the archive. On this PC it is installed in `C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab`. Logs are in its `BanterLabData` child directory. Controlled Folder Access initially blocked deployment; Max granted access and the subsequent shell copy succeeded. No security settings were changed by the agent.

## Generation companion

The companion reads new AI-mode scene events, calls OpenRouter using `OPENROUTER_API_KEY` from its environment, and atomically writes one reply file in the experiment workspace. `BanterLabData/bridge.json` gives the game the absolute `reply_file` path. This keeps the Python 3.13 companion from needing write access to protected Documents. The game polls that file from its own alarm callback; it never waits for an HTTP request. One request is outstanding at a time; old/expired or wrong-zone replies are discarded. API errors stop generated mode rather than pretending a fixed line was generated.

```powershell
py -3.13 '.\companion.py' `
  --data-directory 'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab\BanterLabData' `
  --reply-file 'C:\Users\Max\workspace\github.com\vegerot\ai-conversations\gaming\sims-ai\.local\bridge\reply.json'
```

Then enter `banter.ai` in-game. Stop with `banter.stop` and stop the companion with Ctrl+C. `prompt.txt` is reread for each request, so writing experiments do not require restarting the game. The initial model choice is `openai/gpt-6-luna`, confirmed in the live OpenRouter catalog; `--model` allows an explicit experiment with another model.

To generate from one captured scene without running the bridge:

```powershell
py -3.13 '.\companion.py' --once '.\.local\scene.json'
```

The first working slice is verified: live social hooks, personality/mood/relationship context, three generated exchanges through the companion, and complete generated text visible in the Notification Wall. [Result and samples](experiments/02-context-and-generation/result.json), [in-game screenshot](experiments/02-context-and-generation/in-game.jpg).

Presentation remains experimental: popup cards may collapse to titles, and other installed mods can queue notifications ahead of dialogue. Provider calls took about 4–5 seconds in the live test. The normal path passed; timeout, provider-error, pause, and travel behavior still need dedicated checks before calling this birthday-ready.

The plan and progress files describe this experiment phase. Max expects to replace them when the production build starts; retain useful Sims findings separately.
