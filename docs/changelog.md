# Changelog

## Notable Upgrades

### v3.3.6 — OpenCode Multi-Model Support

New **multi-model mode** for OpenCode: both `opencode.single.json` and `opencode.multi.json` include the full 10-agent setup (orchestrator + 9 sub-agents) with `delegate` tool support.

- Setup scripts ask which mode to use (single vs multi) or accept `--opencode-mode` flag.
- **single.json** — ready to use as-is; all agents inherit the default model.
- **multi.json** — same structure, serves as a template for assigning different models per agent.

### v3.3.5 — Full Setup Scripts

New `setup.sh` (Unix) and `setup.ps1` (Windows) that auto-detect agents, install skills, AND configure orchestrator prompts in one command.

- Idempotent with HTML comment markers — safe to run multiple times.
- `--non-interactive` mode for external installers like [gentle-ai](https://github.com/gentleman-programming/gentleman-ai-installer).
- OpenCode special handling: slash commands + JSON config merge.

### v3.3.1 — Skill Registry

New `skill-registry` skill for creating/updating the registry on demand.

- Orchestrator reads the skill registry once per session and passes pre-resolved skill paths to each sub-agent's launch prompt — sub-agents know about your coding skills (React, TDD, Playwright, etc.) and project conventions without needing to search themselves.
- Engram-first + `.atl/skill-registry.md` fallback — orchestrator resolution works with or without engram.

### v3.3.0 — Mandatory Persist Steps + Knowledge Persistence

Every skill has an explicit numbered "Persist Artifact" step — models were ignoring the contract section and skipping persistence. Now it's impossible to miss.

- Non-SDD sub-agents are instructed to save discoveries, decisions, and bug fixes to engram automatically.

### v3.2.3 — Inline Engram Persistence

All 9 SDD skills now have critical engram calls (`mem_search`, `mem_save`, `mem_get_observation`) inlined directly in their numbered steps. Sub-agents no longer need to follow a 3-hop file read chain to find persistence instructions.

### v2.0 — TDD + Real Execution

- **sdd-apply v2.0** — TDD workflow support. RED-GREEN-REFACTOR cycle when enabled via config.
- **sdd-verify v2.0** — Real test execution + spec compliance matrix (PASS/FAIL/SKIP per requirement).

## Releases

- `v3.3.6` — OpenCode multi-model support: one agent per SDD phase, each with its own model. Setup scripts auto-configure both modes.
- `v3.3.5` — Full setup scripts (`setup.sh` / `setup.ps1`): auto-detect agents + install skills + configure orchestrator prompts in one step.
- `v3.3.4` — Installer fixes: skill-registry included, correct VS Code path.
- `v3.3.3` — Multi-directory skill scanning + correct agent paths from gentle-ai.
- `v3.3.2` — Index file expansion in skill registry + README overhaul.
- `v3.3.1` — Skill registry skill, engram-first discovery, inline persistence in all skills.
