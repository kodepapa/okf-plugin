# okf-plugin

Agent skills for working with [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundles — directories of markdown concept documents with YAML frontmatter that describe data assets, APIs, metrics, playbooks, and other knowledge.

Two skills, usable by Claude Code or any agent that speaks the [Agent Skills](https://agentskills.io) format:

| Skill | What it does |
|---|---|
| [`okf-author`](skills/okf-author/SKILL.md) | Create, edit, and enrich bundles: frontmatter rules, body conventions, cross-linking, `index.md`/`log.md` maintenance, validation. |
| [`okf-read`](skills/okf-read/SKILL.md) | Navigate and answer questions from bundles via progressive disclosure, with the permissive consumption rules the spec requires. |

Each skill is self-contained and bundles `scripts/okf.py`, a zero-dependency helper (PyYAML optional):

```bash
python3 skills/okf-author/scripts/okf.py validate <bundle>   # conformance check (SPEC §9)
python3 skills/okf-author/scripts/okf.py index <bundle> --write  # (re)generate index.md files
python3 skills/okf-author/scripts/okf.py list <bundle>       # concept inventory: id [type] description
```

The validator passes with 0 errors on all three bundles published in Google's knowledge-catalog repo, and `index` round-trips their checked-in `index.md` files byte-identically. The OKF v0.1 spec is vendored at [`skills/okf-author/references/spec.md`](skills/okf-author/references/spec.md) (from [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog), Apache License 2.0).

## Install

**Claude Code (as a plugin):**

```
/plugin marketplace add kodepapa/okf-plugin
/plugin install okf@okf-plugin
```

**Claude Code (as personal skills):** symlink or copy the skill folders into `~/.claude/skills/`:

```bash
ln -s "$(pwd)/skills/okf-author" ~/.claude/skills/okf-author
ln -s "$(pwd)/skills/okf-read" ~/.claude/skills/okf-read
```

**Other agents (Codex, etc.):** point your agent's skills directory at the same folders, e.g. the generic location:

```bash
ln -s "$(pwd)/skills/okf-author" ~/.agents/skills/okf-author
ln -s "$(pwd)/skills/okf-read" ~/.agents/skills/okf-read
```

## Development

`evals/evals.json` holds the test cases and assertions used to benchmark the skills (skill-creator format); `okf-skill-workspace/grade.py` grades runs programmatically against them. Iteration 1: with-skill runs passed 100% of assertions vs 81% for no-skill baselines — the gap comes entirely from creating bundles from scratch, where baselines invent a plausible-but-nonconformant format instead of the actual spec.
