---
name: okf-author
description: Create, edit, and enrich Open Knowledge Format (OKF) bundles — directories of markdown concept documents with YAML frontmatter that describe data assets, APIs, metrics, playbooks, and other knowledge. Use this skill whenever the user wants to create a knowledge bundle, document a dataset/table/schema/API as markdown knowledge, add or update a concept in an existing OKF bundle, maintain index.md or log.md files, or mentions OKF, knowledge bundles, knowledge catalogs, or "markdown + frontmatter" knowledge bases — even if they don't say "OKF" explicitly.
---

# Authoring OKF Bundles

OKF (Open Knowledge Format v0.1) represents knowledge as a plain directory of
markdown files with YAML frontmatter. No SDK, no registry — if you can write a
file, you can produce OKF. Your output will be read verbatim by humans browsing
the repo and by agents loading files into context, so every document must be
clean, self-contained markdown.

The full spec is at `references/spec.md` in this skill — consult it for edge
cases (versioning, conformance details). This file covers everything needed for
day-to-day authoring.

Helper script: `scripts/okf.py` inside this skill's directory (next to this
SKILL.md). Invoke it with its full path, e.g.
`python3 <path-to-this-skill>/scripts/okf.py validate <bundle>`.

## Bundle anatomy

```
bundle/
├── index.md          # reserved: directory listing (no frontmatter, except optional
│                     #   okf_version block at the bundle root only)
├── log.md            # reserved: change history, newest first
├── <concept>.md      # a concept document
└── <group>/          # any directory layout the domain suggests (tables/, metrics/, …)
    ├── index.md
    └── <concept>.md
```

- A **concept** is one markdown file describing one unit of knowledge — a table,
  an API endpoint, a metric, a playbook, anything.
- The **concept ID** is its path minus `.md` (e.g. `tables/users`).
- `index.md` and `log.md` are **reserved** at every level — never use those
  names for concepts.
- Organize directories by what makes sense for the domain; the spec doesn't
  prescribe a taxonomy.

## Writing a concept document

```markdown
---
type: BigQuery Table            # REQUIRED — the only hard requirement in OKF
title: Customer Orders
description: One row per completed customer order across all channels.
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, orders]
timestamp: 2026-07-03T10:00:00Z
---

One to three paragraphs of prose: what this is, what it represents, how it is
used. For tables state the grain ("one row per X"), time range, and any
sampling/obfuscation caveats.

# Schema

| Column     | Type   | Description                      |
|------------|--------|----------------------------------|
| `order_id` | STRING | Globally unique order identifier.|

# Examples

```sql
SELECT ... -- 1–3 short, realistic snippets
```

# Citations

[1] [Source Title](https://example.com/...)
```

Field rules, and why they matter:

- `type` — required, non-empty. Free-form but descriptive (`BigQuery Table`,
  `Metric`, `Playbook`, `API Endpoint`, `Reference`). Consumers route and
  filter on it, so reuse the same string for concepts of the same kind within
  a bundle.
- `description` — ONE tight sentence. It is quoted verbatim in `index.md`
  listings and search snippets; a paragraph here breaks every index.
- `title` — short display name (falls back to filename if omitted).
- `resource` — canonical URI of the underlying asset. Omit for abstract
  concepts (metrics, playbooks).
- `tags` — short strings for cross-cutting categorization.
- `timestamp` — ISO 8601, update on every meaningful change.
- Producers may add any extra keys. When editing an existing document,
  **preserve frontmatter keys you don't recognize** — other tools may depend
  on them.

Body rules:

- Prefer structural markdown (headings, tables, lists, fenced code) over prose
  walls — structure is what makes documents retrievable by agents.
- `# Schema`, `# Examples`, `# Citations` are conventional headings; use them
  when applicable. Other headings are fine too (`# Joins`, `# Steps`, …).
- Ground everything in real metadata. Never invent columns, partitions, or
  URLs. Cite only sources you actually consulted, numbered under
  `# Citations`; when the concept has a `resource`, list it as citation `[1]`.
- No preamble, apologies, or meta-commentary in the body — it must read as a
  finished reference document.

## Cross-linking

Links between concepts are how a bundle becomes a graph instead of a tree.
When prose mentions another concept, link it.

- **Match the bundle's existing link style.** The spec allows bundle-absolute
  (`/tables/users.md`) and file-relative (`../tables/users.md`) links. For new
  bundles default to **file-relative**: they render correctly on GitHub and
  anywhere else the bundle is browsed as plain files.
- Link only to files that exist — check first (`okf.py list` gives the full
  inventory). Broken links are legal in OKF but sloppy in fresh writing.
- One link per concept mention per section is enough; don't over-link.
- Never place links inside headings, fenced code blocks, or schema field-name
  cells.

## The maintenance ritual

Indexes and logs are what make a bundle navigable without loading everything
into context. After creating, renaming, or meaningfully editing any concept:

1. **Update every affected `index.md`** — the listing in the concept's
   directory, and parent listings if a directory was added. Easiest:

   ```bash
   python3 <path-to-this-skill>/scripts/okf.py index <bundle> --write
   ```

   (Run without `--write` first to preview the diff. If the bundle's existing
   indexes are hand-curated with custom grouping, edit them by hand in the
   same style instead of regenerating.)

   Index format — sections of bullets, each `* [Title](url) - description`,
   where the description comes from the target's frontmatter. No frontmatter
   in `index.md` itself (bundle root may carry a small `okf_version: "0.1"`
   block — that's the only exception).

2. **Append to `log.md`** at the bundle root (create it if the bundle has one
   convention-wise; it's optional). Newest first, ISO date headings:

   ```markdown
   ## 2026-07-03
   * **Creation**: Added [Customer Orders](/tables/orders.md) table concept.
   * **Update**: Documented partitioning on [events](/tables/events.md).
   ```

3. **Stamp `timestamp`** in the frontmatter of every document you touched.

## Validate before you finish

```bash
python3 <path-to-this-skill>/scripts/okf.py validate <bundle>
```

Fix all ERRORs (unparseable frontmatter, missing `type`, frontmatter in a
non-root `index.md`) — these are the only hard conformance rules. Review WARNs
(broken links, missing descriptions, malformed log dates) and fix the ones you
introduced; pre-existing warnings in a bundle you're only extending can be
reported to the user instead.

If the script is unavailable, check the same things by hand — parseable
frontmatter and a non-empty `type` on every non-reserved `.md` file is what
makes a bundle conformant.
