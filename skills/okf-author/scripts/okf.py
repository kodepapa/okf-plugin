#!/usr/bin/env python3
"""okf.py — helper for Open Knowledge Format (OKF v0.1) bundles.

Usage:
  okf.py validate <bundle>            # conformance check (exit 1 on errors)
  okf.py index <bundle> [--write]     # generate/refresh index.md files (diff by default)
  okf.py list <bundle>                # one line per concept: id, type, description
  okf.py --selftest                   # run built-in self-check

Errors = spec violations (SPEC.md §9). Warnings = soft guidance; never fail the run.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

RESERVED = {"index.md", "log.md"}
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1\s*$", re.M | re.S)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

try:
    import yaml

    def parse_yaml(text):
        return yaml.safe_load(text)
except ImportError:  # ponytail: naive fallback, install pyyaml for full YAML
    def parse_yaml(text):
        out, key = {}, None
        for line in text.splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            if re.match(r"^\s*-\s", line) and key:
                out.setdefault(key, []).append(line.split("-", 1)[1].strip())
                continue
            m = re.match(r"^(\S[^:]*):\s*(.*)$", line)
            if not m:
                raise ValueError(f"unparseable line: {line!r}")
            key, val = m.group(1).strip(), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                out[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            else:
                out[key] = val.strip("'\"") if val else None
        return out


def split_frontmatter(text):
    """Return (frontmatter_dict_or_None, body). Raises on unparseable YAML."""
    if not text.startswith("---"):
        return None, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("unterminated frontmatter block")
    fm = parse_yaml(m.group(1))
    if fm is not None and not isinstance(fm, dict):
        raise ValueError("frontmatter is not a YAML mapping")
    return fm, m.group(2)


def iter_md(bundle):
    return sorted(p for p in bundle.rglob("*.md") if not any(part.startswith(".") for part in p.parts))


def concept_id(bundle, path):
    return str(path.relative_to(bundle)).removesuffix(".md")


def load_concepts(bundle):
    """Yield (path, frontmatter, body, error_string_or_None) for non-reserved .md files."""
    for p in iter_md(bundle):
        if p.name in RESERVED:
            continue
        try:
            fm, body = split_frontmatter(p.read_text(encoding="utf-8"))
            yield p, fm, body, None
        except Exception as e:
            yield p, None, "", str(e)


def check_links(bundle, path, body, warn):
    body = FENCE_RE.sub("", body)
    for _, target in LINK_RE.findall(body):
        target = target.split("#")[0]
        if not target or "://" in target or target.startswith(("mailto:", "tel:")):
            continue
        resolved = (bundle / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
        try:
            resolved = resolved.resolve()
            if not resolved.exists():
                warn(f"{path.relative_to(bundle)}: broken link -> {target}")
        except OSError:
            warn(f"{path.relative_to(bundle)}: unresolvable link -> {target}")


def cmd_validate(bundle):
    errors, warnings = [], []
    for p, fm, body, err in load_concepts(bundle):
        rel = p.relative_to(bundle)
        if err:
            errors.append(f"{rel}: frontmatter error: {err}")
            continue
        if fm is None:
            errors.append(f"{rel}: missing frontmatter block")
            continue
        if not str(fm.get("type") or "").strip():
            errors.append(f"{rel}: missing or empty required field 'type'")
        if not str(fm.get("description") or "").strip():
            warnings.append(f"{rel}: no 'description' (used by index generators)")
        check_links(bundle, p, body, warnings.append)
    for p in iter_md(bundle):
        rel, text = p.relative_to(bundle), p.read_text(encoding="utf-8")
        if p.name == "index.md" and text.startswith("---") and p.parent != bundle:
            errors.append(f"{rel}: frontmatter only allowed in bundle-root index.md")
        if p.name == "log.md":
            for h in re.findall(r"^##\s+(.+)$", text, re.M):
                if not DATE_RE.match(h.strip()):
                    warnings.append(f"{rel}: log heading '{h.strip()}' is not ISO YYYY-MM-DD")
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def entry_line(title, url, desc):
    return f"* [{title}]({url})" + (f" - {desc}" if desc else "")


def build_index(bundle, directory):
    """Render an index.md body for one directory from its concepts and subdirs."""
    existing_desc = {}
    idx = directory / "index.md"
    if idx.exists():
        for _, url, desc in re.findall(r"^\*\s*\[([^\]]*)\]\(([^)]+)\)\s*(?:-\s*(.*))?$",
                                       idx.read_text(encoding="utf-8"), re.M):
            if desc:
                existing_desc[url] = desc.strip()
    groups = {}
    for p in sorted(directory.glob("*.md")):
        if p.name in RESERVED:
            continue
        try:
            fm, _ = split_frontmatter(p.read_text(encoding="utf-8"))
        except Exception:
            fm = None
        fm = fm or {}
        title = fm.get("title") or p.stem.replace("_", " ").replace("-", " ").title()
        groups.setdefault(fm.get("type") or "Concepts", []).append(
            entry_line(title, p.name, fm.get("description"))
        )
    subdirs = []
    for d in sorted(x for x in directory.iterdir() if x.is_dir() and not x.name.startswith(".")):
        concepts = [p for p in d.rglob("*.md") if p.name not in RESERVED]
        if not concepts:
            continue
        url = f"{d.name}/index.md"
        desc = existing_desc.get(url)  # keep hand-curated subdir summaries
        if desc is None and len(concepts) == 1:
            try:
                fm, _ = split_frontmatter(concepts[0].read_text(encoding="utf-8"))
                desc = (fm or {}).get("description")
            except Exception:
                pass
        subdirs.append(entry_line(d.name, url, desc))
    sections = []
    if subdirs:
        sections.append("# Subdirectories\n\n" + "\n".join(subdirs))
    for typ in sorted(groups):
        sections.append(f"# {typ}\n\n" + "\n".join(groups[typ]))
    return "\n\n".join(sections) + "\n" if sections else ""


def cmd_index(bundle, write):
    changed = 0
    dirs = {bundle} | {p.parent for p in iter_md(bundle)}
    for d in sorted(dirs):
        new = build_index(bundle, d)
        if not new:
            continue
        idx = d / "index.md"
        old = idx.read_text(encoding="utf-8") if idx.exists() else ""
        if old == new:
            continue
        changed += 1
        if write:
            idx.write_text(new, encoding="utf-8")
            print(f"wrote {idx.relative_to(bundle)}")
        else:
            rel = str(idx.relative_to(bundle))
            sys.stdout.writelines(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
    print(f"{changed} index file(s) {'written' if write else 'would change (use --write)'}")
    return 0


def cmd_list(bundle):
    for p, fm, _, err in load_concepts(bundle):
        fm = fm or {}
        typ = fm.get("type") or ("?" if not err else "!ERROR")
        desc = (fm.get("description") or "").strip()
        print(f"{concept_id(bundle, p)}  [{typ}]  {desc}")
    return 0


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp)
        (b / "tables").mkdir()
        (b / "tables/orders.md").write_text(
            "---\ntype: Table\ntitle: Orders\ndescription: One row per order.\n---\n\n"
            "See [customers](/tables/customers.md) and [missing](./nope.md).\n")
        (b / "tables/customers.md").write_text("---\ntype: Table\ndescription: Customers.\n---\nBody.\n")
        (b / "bad.md").write_text("no frontmatter here\n")
        (b / "log.md").write_text("# Log\n\n## 2026-07-03\n* **Creation**: init.\n\n## not-a-date\n* x\n")
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_validate(b)
        text = out.getvalue()
        assert rc == 1, text
        assert "bad.md: missing frontmatter" in text
        assert "broken link -> ./nope.md" in text
        assert "not-a-date" in text
        assert "customers.md" not in [l for l in text.splitlines() if l.startswith("ERROR")]
        cmd_index(b, write=True)
        idx = (b / "tables/index.md").read_text()
        assert "[Orders](orders.md) - One row per order." in idx
        assert idx.startswith("# Table")
    print("selftest OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["validate", "index", "list"])
    ap.add_argument("bundle", nargs="?", type=Path)
    ap.add_argument("--write", action="store_true", help="apply index changes")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.command or not a.bundle or not a.bundle.is_dir():
        ap.error("need a command and an existing bundle directory")
    sys.exit({"validate": lambda: cmd_validate(a.bundle),
              "index": lambda: cmd_index(a.bundle, a.write),
              "list": lambda: cmd_list(a.bundle)}[a.command]())


if __name__ == "__main__":
    main()
