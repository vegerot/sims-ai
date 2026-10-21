# Birthday mod: experiment plan

## Goal

The long-term goal is to replace Simlish speech with contextual spoken English throughout gameplay. Learn how to produce enjoyable English dialogue for actual Sims social interactions, then use the findings to plan a small, dependable birthday gift for October 29, 2026. The birthday scope will be selected from experiments; full speech replacement is not yet a proven release target.

Her priorities are relationships and drama, dream homes/restaurants, and food. Match The Sims' energy: distinct personalities and relationships, with playful and occasionally absurd situations. Food is relevant when it is part of the scene; it is not a mandatory theme.

## Settled boundaries

- Start with automatic character-to-character banter. The human player watches normal social interactions.
- Start with text. Spoken English, direct player conversation, narration, and model-selected actions are independent future experiments.
- The game chooses actions. The dialogue observes them; text must not pretend to execute actions.
- Prove the integration with a fixed test line before adding generated banter.
- Develop on this PC. Prefer to preserve the surprise, but secrecy is not a hard constraint.
- Test using a separate save. Back up original save contents and hashes, including the shared autosave, before testing; restore/check them after closing the game. Preserve existing mods.
- Keep reusable knowledge in [how-sims-works.md](how-sims-works.md), vocabulary in [CONTEXT.md](CONTEXT.md), and primary-source research in [planning.md](planning.md).

## Experiments

1. **Social hook and text.** Package a small Python script mod for the installed game. Keep it dormant until explicitly started. Observe a real social interaction, identify actor and target, display a clearly labeled fixed line, and record evidence. Confirm ordinary actions continue to work.
2. **Useful context.** Capture readable interaction information, participant names, personality traits, moods, and relationship context where verified. Inspect real samples before deciding what the prompt needs.
3. **Generated banter.** Generate a short exchange from that context. Keep network/model work off the game thread and deliver notifications from game callbacks. Measure turnaround and judge the tone. Use existing model access if suitable; record actual provider/model and costs when checked.
4. **Reassess.** Review what is fun, reliable, and difficult. Choose the birthday scope from evidence. Plan independent voice, player-conversation, narration, or action experiments only as needed.

## Keep the experiment small

Challenge requirements before implementing them. Omit a general agent framework, autonomous world control, vector memory, broad provider abstractions, custom UI, and voice infrastructure from the first proof. Simplify what survives. Shorten iteration once the integration works, then automate only a demonstrated workflow.

Prior-art source and inspection of the installed bytecode support a narrow script-hook approach, rather than starting with native reverse engineering. See [mechanisms and evidence](how-sims-works.md). Source inspection does not establish successful gameplay.

## Evidence of success

- A real social interaction produces an in-game notification with the correct participants and a recorded interaction identifier.
- The original game callback still executes normally.
- Context fields used for generation are observed or explicitly marked unavailable.
- Generated text is attributable to the correct Sims, reflects the interaction, and sounds appropriate for The Sims.
- API failure or absent generation does not freeze the game or masquerade as completed gameplay.
- Existing save-file hashes are checked against the pre-test manifest.
- The experimental installation and commands are documented and easy to remove or disable.

## Handoff and lifecycle

Read this plan, then the newest [progress entries](progress.md); compare the handoff with the working copy and relevant live state. Progress entries are append-only and end with a concrete `Next:` block. Keep changing state out of this plan.

These are experiment-phase documents. When Max decides to begin the production build, replace them with a new plan and progress log based on the selected scope. Preserve reusable knowledge and relevant evidence rather than treating the experimental code or architecture as a commitment.
