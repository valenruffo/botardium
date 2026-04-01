Reference documentation for the SDD phase sub-agents and skill system. For quick start, see the [main README](../README.md).

# Sub-Agents & Skill Registry

## SDD Phase Sub-Agents

Each sub-agent is a SKILL.md file — pure Markdown instructions that any AI assistant can follow. The orchestrator resolves skill paths from the [skill registry](#skill-registry) and passes them directly in each sub-agent's launch prompt — sub-agents receive ready-to-use paths, not a search task.

| Sub-Agent | Skill File | What It Does |
|-----------|-----------|-------------|
| **Init** | `sdd-init/SKILL.md` | Detects project stack, bootstraps persistence, builds skill registry |
| **Explorer** | `sdd-explore/SKILL.md` | Reads codebase, compares approaches, identifies risks |
| **Proposer** | `sdd-propose/SKILL.md` | Creates `proposal.md` with intent, scope, rollback plan |
| **Spec Writer** | `sdd-spec/SKILL.md` | Writes delta specs (ADDED/MODIFIED/REMOVED) with Given/When/Then |
| **Designer** | `sdd-design/SKILL.md` | Creates `design.md` with architecture decisions and rationale |
| **Task Planner** | `sdd-tasks/SKILL.md` | Breaks down into phased, numbered task checklist |
| **Implementer** | `sdd-apply/SKILL.md` | Writes code following specs and design, marks tasks complete. v2.0: TDD workflow support |
| **Verifier** | `sdd-verify/SKILL.md` | Validates implementation against specs with real test execution. v2.0: spec compliance matrix |
| **Archiver** | `sdd-archive/SKILL.md` | Merges delta specs into main specs, moves to archive |
| **Skill Registry** | `skill-registry/SKILL.md` | Scans user skills + project conventions, writes `.atl/skill-registry.md` |

### Sub-Agent Result Contract

Each sub-agent must return a structured envelope with these fields:

| Field | Description |
|-------|-------------|
| `status` | `success`, `partial`, or `blocked` |
| `executive_summary` | 1-3 sentence summary of what was done |
| `detailed_report` | (optional) Full phase output, or omit if already inline |
| `artifacts` | List of artifact keys/paths written |
| `next_recommended` | The next SDD phase to run, or "none" |
| `risks` | Risks discovered, or "None" |

Example:

```markdown
**Status**: success
**Summary**: Proposal created for `{change-name}`. Defined scope, approach, and rollback plan.
**Artifacts**: Engram `sdd/{change-name}/proposal` | `openspec/changes/{change-name}/proposal.md`
**Next**: sdd-spec or sdd-design
**Risks**: None
```

`executive_summary` is intentionally short. `detailed_report` can be as long as needed for complex architecture work.

### Sub-Agent Context Protocol

Sub-agents start with a **fresh context** — they don't know what user skills exist (React, TDD, Playwright, etc.). The orchestrator controls context access.

Each sub-agent receives the **pre-resolved paths** directly in its launch prompt — no registry search needed. Sub-agents do NOT search for the registry themselves.

Sub-agents are also instructed to save discoveries, decisions, and bug fixes to engram automatically (non-SDD sub-agents) or via the mandatory persist step (SDD phases).

---

## Shared Conventions

All skills reference three shared convention files in `skills/_shared/`. Critical engram calls (`mem_search`, `mem_save`, `mem_get_observation`) are also **inlined directly in each skill** so sub-agents don't need to follow multi-hop file references.

| File | Purpose |
|------|---------|
| `persistence-contract.md` | Mode resolution rules, sub-agent context protocol, skill registry loading protocol |
| `engram-convention.md` | Supplementary reference for deterministic naming (`sdd/{change-name}/{artifact-type}`) and two-step recovery. Critical calls are inlined in skills. |
| `openspec-convention.md` | Filesystem paths for each artifact, directory structure, config.yaml reference, and archive layout |

**Why inline + shared:**
- **Sub-agents fail multi-hop chains** — A 3-hop read chain (skill → convention file → actual instructions) breaks non-Claude models. Inlining the critical calls eliminates this.
- **Deterministic recovery** — Engram artifact naming follows a strict `sdd/{change}/{type}` convention with `topic_key`, so any skill can reliably find artifacts created by other skills.
- **Consistent mode behavior** — All skills resolve `engram | openspec | hybrid | none` the same way. `openspec` and `hybrid` are never chosen automatically.

---

## Skill Registry

Sub-agents start with a **fresh context** — they don't know what user skills exist (React, TDD, Playwright, etc.). The skill registry solves this — but the key is **who reads it**.

**How it works:**
1. `/sdd-init` or `/skill-registry` scans your installed skills and project conventions
2. Writes `.atl/skill-registry.md` in the project root (mode-independent, always created)
3. If engram is available, also saves to engram (cross-session bonus)
4. The **orchestrator** reads the registry once per session and resolves the relevant skill paths
5. Each sub-agent receives the **pre-resolved paths** directly in its launch prompt — no registry search needed

**Orchestrator reads the registry. Sub-agents receive paths. Sub-agents do NOT search for the registry.**

**Orchestrator read priority:** Engram first (fast, survives compaction) → `.atl/skill-registry.md` as fallback.

**What it contains:**
- User skills table: trigger → skill name → path (e.g., "React components" → `react-19` → `~/.claude/skills/react-19/SKILL.md`)
- Project conventions found: `agents.md`, `CLAUDE.md`, `.cursorrules`, etc.

**When to update:** Run `/skill-registry` after installing or removing skills.
