---
name: okf-read
description: Navigate, explore, and answer questions from Open Knowledge Format (OKF) bundles — directories of markdown concept documents with YAML frontmatter describing data assets, metrics, APIs, and playbooks. Use this skill whenever the user points you at a knowledge bundle or markdown knowledge catalog and asks what's in it, how tables relate or join, what a metric means, or any question the bundle should answer — even if they don't call it "OKF". Also use it before answering data questions in a repo that contains a bundle of markdown files with YAML frontmatter.
---

# Reading OKF Bundles

An OKF bundle is a directory of markdown concept documents with YAML
frontmatter. It is designed for **progressive disclosure**: you can find the
right concept by walking indexes instead of loading the whole tree into
context. Read only what the question needs.

## Navigation

1. Start at the bundle root `index.md` — it lists subdirectories and top-level
   concepts, each with a one-line description.
2. Drill down one level at a time via directory `index.md` files until the
   descriptions point you at the relevant concepts. Only then open the concept
   files themselves.
3. No `index.md`? Get an inventory instead of globbing blind:

   ```bash
   python3 <path-to-this-skill>/scripts/okf.py list <bundle>
   ```

   prints `concept_id  [type]  description` for every concept — one grep-able
   line each. (The script lives in `scripts/` next to this SKILL.md.)

## Reading a concept

- Frontmatter carries the queryable facts: `type` (kind of concept), `title`,
  `description`, `resource` (URI of the real asset), `tags`, `timestamp`.
- The body is the knowledge: prose, `# Schema` tables, `# Examples` snippets,
  `# Citations` sources.
- Markdown links between concepts are relationship edges (joins-with,
  parent-of, depends-on — the prose around the link says which). Follow them
  to gather related context; the link graph is often more informative than the
  directory tree.
- Links starting with `/` are relative to the **bundle root**, not the
  filesystem root.

## Be permissive (the spec requires it)

Real bundles are living documents, partially agent-generated. Per SPEC §9,
never reject or distrust a bundle because of unknown `type` values, missing
optional fields, broken links (they often mark not-yet-written knowledge),
missing indexes, or extra frontmatter keys. Work with what's there and note
gaps in your answer rather than failing.

## Answering questions

- Cite the concept files you used (by concept ID or path) so the user can
  verify.
- Distinguish what the bundle states from what you infer; flag when the
  bundle's `timestamp`s suggest the knowledge may be stale.
- If the user then wants to fix or extend the bundle, switch to the
  `okf-author` skill — it covers frontmatter rules, index/log maintenance, and
  validation.
