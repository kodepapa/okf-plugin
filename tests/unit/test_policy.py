from __future__ import annotations

from pathlib import Path

from okfleet.core import load_bundle
from okfleet.policy import load_policy, policy_diagnostics


def test_policy_pack_requires_type_specific_field(bundle_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "policy.toml"
    path.write_text(
        '[policy]\nallowed_types = ["Metric", "Table"]\n'
        '[policy.required_by_type]\nMetric = ["owner"]\n',
        encoding="utf-8",
    )
    diagnostics = policy_diagnostics(load_bundle(bundle_path), load_policy(path))
    assert [item.code for item in diagnostics] == ["POLICY_REQUIRED_FIELD"]


def test_policy_pack_enforces_freshness_target(bundle_path: Path) -> None:
    diagnostics = policy_diagnostics(load_bundle(bundle_path), {"freshness_by_type": {"Table": 30}})
    assert any(item.code == "POLICY_FRESHNESS_TIMESTAMP" for item in diagnostics)
