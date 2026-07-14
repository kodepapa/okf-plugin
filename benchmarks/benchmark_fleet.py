from __future__ import annotations

import argparse
import shutil
import tempfile
import time
from pathlib import Path

from okfleet.core import load_bundle
from okfleet.models import BundleRef
from okfleet.search import SearchDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure OKFleet index/search latency.")
    parser.add_argument("--bundles", type=int, default=20)
    parser.add_argument("--copies", type=int, default=250, help="Concept copies per bundle.")
    args = parser.parse_args()
    demo = Path(__file__).parents[1] / "examples/demo-bundle"
    with tempfile.TemporaryDirectory(prefix="okfleet-benchmark-") as temporary:
        root = Path(temporary)
        refs: list[BundleRef] = []
        for bundle_number in range(args.bundles):
            bundle_root = root / f"bundle-{bundle_number}"
            shutil.copytree(demo, bundle_root)
            template = (bundle_root / "metrics/net-revenue.md").read_text(encoding="utf-8")
            for concept_number in range(args.copies):
                path = bundle_root / "generated" / f"metric-{concept_number}.md"
                path.parent.mkdir(exist_ok=True)
                path.write_text(
                    template.replace("Net Revenue", f"Metric {concept_number}"),
                    encoding="utf-8",
                )
            refs.append(BundleRef(str(bundle_number), f"bundle-{bundle_number}", bundle_root))
        with SearchDatabase(root / "fleet.db") as database:
            started = time.perf_counter()
            changed = sum(database.index_bundle(ref, load_bundle(ref.path)) for ref in refs)
            index_seconds = time.perf_counter() - started
            started = time.perf_counter()
            hits = database.search("revenue", limit=20)
            search_seconds = time.perf_counter() - started
        print(
            {
                "bundles": args.bundles,
                "concepts": changed,
                "index_seconds": round(index_seconds, 3),
                "search_milliseconds": round(search_seconds * 1000, 3),
                "hits": len(hits),
            }
        )


if __name__ == "__main__":
    main()
