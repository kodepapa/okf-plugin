from pathlib import Path


def test_skill_helpers_are_identical() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "skills/okf-author/scripts/okf.py").read_bytes() == (
        root / "skills/okf-read/scripts/okf.py"
    ).read_bytes()
