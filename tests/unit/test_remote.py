from __future__ import annotations

from pathlib import Path

from okfleet.remote import remote_destination


def test_remote_destination_is_scoped_and_slugged(tmp_path: Path) -> None:
    destination = remote_destination("https://example.com/team/Knowledge.git", tmp_path)
    assert destination.parent == tmp_path
    assert destination.name.startswith("knowledge-")
