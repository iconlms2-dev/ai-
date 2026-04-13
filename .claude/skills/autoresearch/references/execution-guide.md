# How to Run the Target Skill

Each experiment requires running the target skill with test inputs and collecting its outputs. Choose the method that fits your setup.

## Method 1: Subagent (recommended)

Use the `Agent` tool to spawn a subagent that executes the skill in the target project's working directory. The subagent inherits the project's CLAUDE.md and skill definitions, so it behaves exactly as a user would experience. Include the target project path as a `cd` instruction inside the prompt — the Agent tool has no `cwd` parameter.

```
Agent(prompt="Your working directory is /path/to/project. Run: <test prompt>", subagent_type="general-purpose")
```

## Method 2: Direct execution

If the skill can run in the current session (same project), execute it directly — read the skill's CLAUDE.md, follow its workflow, and produce outputs. This is simplest but means you are both the optimizer and the executor, which can bias results.

## Key rules

- Never use external services, APIs, or intermediary servers to run the skill. Run everything locally in Claude Code.
- Each experiment must start from a clean state — don't let outputs from one experiment leak into the next.
- If the skill takes longer than 10 minutes per prompt, reduce the test scope (fewer items, simpler sites) rather than increasing timeouts.
- **Save all outputs into `runs/exp-N/<prompt-id>/`** — copy or move every artifact the skill produces (files, screenshots, generated code, etc.) into the experiment's run folder. Never leave experiment outputs only in the skill's native output directory.
