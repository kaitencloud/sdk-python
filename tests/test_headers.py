# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Every Python file opens with the project's license notice, generated ones included.

The notice is what tells a reader of a single file -- copied out of the repository, vendored,
read on a code search -- under which terms it may be used, without the LICENSE next to it. A
file that lacks it is caught here, rather than by a license scanner after a release.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contract import ROOT

HEADER = ["# Copyright 2026 KAITEN INC", "# SPDX-License-Identifier: Apache-2.0"]
FILES = sorted(
    path
    for folder in ("src/kaitencloud", "scripts", "tests", "examples")
    for path in (ROOT / folder).rglob("*.py")
)


def test_there_are_files_to_check() -> None:
    assert len(FILES) > 50


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_python_file_opens_with_the_license_notice(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]  # a script's interpreter line has to come first
    assert lines[:2] == HEADER, f"{path.relative_to(ROOT)} lacks the license notice"
