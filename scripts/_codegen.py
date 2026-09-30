# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Shared plumbing for the code generators: format like the project, then write or compare.

Both generators (``generate_models.py`` and ``unasync.py``) produce committed files. They
render into a scratch directory, run ruff over it with the project's own configuration, and
only then compare with -- or copy over -- what is on disk. Formatting before comparing is
what lets ``--check`` be exact: a stale file is a real difference, never a whitespace one.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LICENSE_HEADER = "# Copyright 2026 KAITEN INC\n# SPDX-License-Identifier: Apache-2.0\n"
"""The notice every Python file of the project opens with, generated ones included."""


def emit(files: Mapping[Path, str], *, check: bool, orphans: Iterable[Path] = ()) -> bool:
    """Write ``files`` (absolute path -> content), or report the ones that are stale.

    ``orphans`` are generated files that no longer have a source; they are deleted, or
    reported under ``check``. Returns ``True`` when the tree already matched.
    """
    with tempfile.TemporaryDirectory() as scratch:
        staged: dict[Path, Path] = {}
        for target, content in sorted(files.items()):
            path = Path(scratch) / target.relative_to(ROOT)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            staged[target] = path

        if staged:
            _ruff("check", "--select", "I,F401,RUF022", "--fix", "--exit-zero", *staged.values())
            _ruff("format", *staged.values())

        stale = [
            target
            for target, path in staged.items()
            if not target.exists()
            or target.read_text(encoding="utf-8") != path.read_text(encoding="utf-8")
        ]
        leftovers = sorted(path for path in orphans if path.exists())

        if check:
            for path in stale:
                print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
            for path in leftovers:
                print(f"orphaned: {path.relative_to(ROOT)}", file=sys.stderr)
            return not stale and not leftovers

        for target in stale:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staged[target], target)
            print(f"wrote {target.relative_to(ROOT)}")
        for path in leftovers:
            path.unlink()
            print(f"removed {path.relative_to(ROOT)}")
        return not stale and not leftovers


def _ruff(command: str, *args: object) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            command,
            "--config",
            str(ROOT / "pyproject.toml"),
            "--quiet",
            *(str(arg) for arg in args),
        ],
        check=True,
    )
