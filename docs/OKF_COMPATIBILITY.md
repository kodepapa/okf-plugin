# OKF compatibility

OKFleet targets Open Knowledge Format v0.1 bundles: Markdown concept documents with YAML frontmatter, directory indexes, and optional logs.

The parser is deliberately forward-compatible. Unknown frontmatter fields and concept types are preserved, and malformed documents become diagnostics instead of crashing a fleet scan. Concept IDs derive from bundle-relative Markdown paths. Links may be relative Markdown links or root-relative bundle links; graph and backlink tools resolve both conservatively.

Validation distinguishes hard errors from maintenance warnings. It checks required metadata, duplicate IDs, broken links, orphan concepts, staleness, generated-index drift, and common type-specific fields. Curated indexes are not silently replaced; index operations preview changes unless `--write` is supplied.

The original dependency-free helpers remain embedded in both skills and continue to support:

```text
python scripts/okf.py validate BUNDLE
python scripts/okf.py index BUNDLE [--write]
python scripts/okf.py list BUNDLE
```

`tools/verify_generated.py` enforces byte equality between the skill copies. The installable OKFleet library is the richer canonical implementation for registry, search, graph, TUI, MCP, providers, and safe mutations.
