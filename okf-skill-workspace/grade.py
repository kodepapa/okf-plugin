#!/usr/bin/env python3
"""Grade an iteration's runs against eval assertions -> grading.json per run.

Usage: python3 grade.py <iteration-dir>
"""
import json
import re
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
OKF = WS.parent / "skills/okf-author/scripts/okf.py"
FIXTURE_GA4 = WS / "fixtures/ga4"


def validate(bundle):
    r = subprocess.run([sys.executable, OKF, "validate", str(bundle)], capture_output=True, text=True)
    m = re.search(r"(\d+) error\(s\), (\d+) warning\(s\)", r.stdout)
    errs, warns = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
    return errs, warns, (r.stdout + r.stderr).strip()


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def frontmatter(p):
    m = re.match(r"^---\s*\n(.*?)\n---", read(p), re.S)
    if not m:
        return {}
    try:
        import yaml
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}


def grade_eval0(out):
    b = out / "shop-kb"
    res = []
    if not b.is_dir():
        # every assertion fails if there is no bundle
        return [("bundle exists at shop-kb", False, "no shop-kb directory produced")]
    errs, warns, log = validate(b)
    res.append(("okf.py validate reports 0 errors", errs == 0, log.splitlines()[-1] if log else ""))
    mds = [p for p in b.rglob("*.md") if p.name not in ("index.md", "log.md")]
    stems = [p.stem for p in mds]

    def norm(s):
        return s.replace("-", "_").rstrip("s").replace("_item", "_items").rstrip("s")

    def doc_for(table):
        return next((p for p in mds if norm(p.stem) == norm(table) or table in p.stem), None)

    missing = [t for t in ("customers", "products", "orders", "order_items") if not doc_for(t)]
    res.append(("all four DDL tables have a concept document", not missing,
                f"concepts: {stems}; missing: {missing or 'none'}"))
    warn_lines = [l for l in log.splitlines() if l.startswith("WARN")]
    res.append(("okf.py validate reports 0 warnings", warns == 0, "; ".join(warn_lines) or "clean"))
    root_idx = read(b / "index.md")
    res.append(("bundle root contains an index.md listing contents",
                bool(re.search(r"\[.+\]\(.+\)", root_idx)), (root_idx[:120] or "missing/empty")))
    logmd = read(b / "log.md")
    dates = re.findall(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$", logmd, re.M)
    res.append(("log.md exists with ISO date headings", bool(dates),
                f"dates: {dates}" if dates else ("log.md missing" if not logmd else "no ISO headings")))
    linked = []
    for p in mds:
        for _, tgt in re.findall(r"\[([^\]]*)\]\(([^)\s]+)\)", read(p)):
            tgt = tgt.split("#")[0]
            if "://" in tgt or not tgt.endswith(".md"):
                continue
            resolved = (b / tgt.lstrip("/")) if tgt.startswith("/") else (p.parent / tgt)
            if resolved.exists() and resolved.name not in ("index.md", "log.md"):
                linked.append(f"{p.stem}->{tgt}")
    res.append(("concepts cross-link related tables with resolvable links", bool(linked),
                "; ".join(linked[:6]) or "no concept-to-concept links found"))
    key_cols = {"customers": ["email", "country_code"], "products": ["sku", "unit_price_usd"],
                "orders": ["status", "placed_at"], "order_items": ["quantity", "unit_price_usd"]}
    bad = []
    for t, cols in key_cols.items():
        p = doc_for(t)
        doc = read(p) if p else ""
        if not re.search(r"^#+\s*Schema", doc, re.M) or not all(c in doc for c in cols):
            bad.append(t)
    res.append(("each table concept has a # Schema section covering DDL columns", not bad,
                f"incomplete: {bad or 'none'}"))
    return res


def grade_eval1(out):
    b = out / "ga4"
    res = []
    new = b / "references/metrics/purchase_conversion_rate.md"
    fm = frontmatter(new)
    desc = str(fm.get("description") or "")
    ok = new.exists() and str(fm.get("type") or "").strip() and desc.strip() and len(desc) < 250
    res.append(("purchase_conversion_rate.md exists with type + one-sentence description", bool(ok),
                f"type={fm.get('type')!r} desc={desc[:100]!r}" if new.exists() else "file missing"))
    idx = read(b / "references/metrics/index.md")
    res.append(("metrics/index.md lists the new metric", "purchase_conversion_rate" in idx,
                next((l for l in idx.splitlines() if "purchase_conversion_rate" in l), "not listed")))
    errs, warns, log = validate(b)
    res.append(("modified ga4 bundle validates with 0 errors", errs == 0,
                log.splitlines()[-1] if log else ""))
    body = read(new)
    has_sql = "```sql" in body
    ratio = bool(re.search(r"/", body)) and "user" in body.lower()
    res.append(("new concept has a fenced sql example expressing purchasers / total users",
                has_sql and ratio, body[body.find("```sql"):body.find("```sql") + 200] if has_sql else "no sql fence"))
    tags = fm.get("tags") or []
    style = fm.get("type") == "Reference" and "metric" in [str(t) for t in tags] and re.search(r"^#+\s*Citations", body, re.M)
    res.append(("style matches sibling metrics (Reference type, metric tag, citations section)",
                bool(style), f"type={fm.get('type')!r} tags={tags} citations={'yes' if re.search(r'Citations', body) else 'no'}"))
    orig = {str(p.relative_to(FIXTURE_GA4)) for p in FIXTURE_GA4.rglob("*.md")}
    now = {str(p.relative_to(b)) for p in b.rglob("*.md")} if b.is_dir() else set()
    gone = sorted(orig - now)
    res.append(("no pre-existing ga4 documents were removed", not gone, f"missing: {gone or 'none'}"))
    return res


def grade_eval2(out):
    res = []
    ans = read(out / "answer.md").lower()
    res.append(("answer.md exists", bool(ans), f"{len(ans)} chars" if ans else "missing"))
    res.append(("identifies the events_ table as the source", "events_" in ans or "events table" in ans,
                "mentions events_" if "events_" in ans else "no events_ mention"))
    fields = {"purchase_revenue": "purchase_revenue" in ans or "purchase revenue" in ans,
              "session grouping (ga_session_id/user_pseudo_id)": "ga_session_id" in ans or "user_pseudo_id" in ans,
              "purchase event filter": "purchase" in ans and "event" in ans}
    res.append(("mentions the key fields (revenue, session/user ids, purchase event)",
                all(fields.values()), str(fields)))
    calc = "average" in ans or "avg" in ans
    res.append(("states the calculation: average per-session spend per user",
                calc and "session" in ans and "user" in ans, "heuristic keyword check"))
    cites = "avg_spend_per_purchase_session_by_user" in ans or "events_.md" in ans
    res.append(("cites bundle document paths", cites, "cites concept path" if cites else "no concept paths found"))
    r = subprocess.run(["diff", "-rq", str(FIXTURE_GA4), str(out / "ga4")], capture_output=True, text=True)
    res.append(("ga4 bundle was not modified", r.returncode == 0, r.stdout.strip() or "identical"))
    return res


GRADERS = {"eval-0": grade_eval0, "eval-1": grade_eval1, "eval-2": grade_eval2}


def main():
    it = Path(sys.argv[1])
    for evdir in sorted(it.glob("eval-*")):
        key = "-".join(evdir.name.split("-")[:2])
        for run in ("with_skill", "without_skill", "old_skill"):
            out = evdir / run / "outputs"
            if not out.is_dir():
                continue
            checks = GRADERS[key](out)
            n = sum(1 for _, p, _ in checks if p)
            grading = {
                "expectations": [{"text": t, "passed": bool(p), "evidence": str(e)[:500]}
                                 for t, p, e in checks],
                "summary": {"passed": n, "failed": len(checks) - n, "total": len(checks),
                            "pass_rate": round(n / len(checks), 4)},
            }
            text = json.dumps(grading, indent=2)
            (evdir / run / "grading.json").write_text(text)
            run1 = evdir / run / "run-1"  # layout aggregate_benchmark.py expects
            run1.mkdir(exist_ok=True)
            (run1 / "grading.json").write_text(text)
            timing = evdir / run / "timing.json"
            if timing.exists():
                (run1 / "timing.json").write_text(timing.read_text())
            print(f"{evdir.name}/{run}: {n}/{len(checks)} passed")


if __name__ == "__main__":
    main()
