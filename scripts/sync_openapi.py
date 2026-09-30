#!/usr/bin/env python3
# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Copy the API contract from a kaiten checkout into ``openapi/``, recording where it came from.

Usage::

    uv run python scripts/sync_openapi.py --kaiten ../kaiten --ref origin/main [--fetch]

The snapshots are read from a git revision of the checkout, never from its working tree, so
what lands here is a committed state of the contract rather than someone's local edit. Run
``task generate`` afterwards -- ``task sync:openapi`` does both -- then let the tests say what
the new contract changed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "openapi.yaml": "app/openapi.yaml",
    "platform-openapi.yaml": "app/platform-openapi.yaml",
}

SOURCE = """\
# Where the two snapshots in this directory were copied from. Rewritten by
# `task sync:openapi`; never edit the snapshots themselves by hand.
repository: kaitencloud/kaiten
ref: {ref}
commit: {commit}
synced_at: "{today}"
files:
  openapi.yaml: app/openapi.yaml
  platform-openapi.yaml: app/platform-openapi.yaml
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the API contract from a kaiten checkout.")
    parser.add_argument("--kaiten", default="../kaiten", help="path to the kaiten checkout")
    parser.add_argument("--ref", default="origin/main", help="the revision to copy from")
    parser.add_argument("--fetch", action="store_true", help="git fetch origin first")
    args = parser.parse_args()

    kaiten = Path(args.kaiten).resolve()
    if not (kaiten / ".git").exists():
        print(f"{kaiten} is not a git checkout of kaitencloud/kaiten", file=sys.stderr)
        return 1

    if args.fetch:
        git(kaiten, "fetch", "--quiet", "origin")
    commit = git(kaiten, "rev-parse", "--verify", f"{args.ref}^{{commit}}").strip()

    for target, source in FILES.items():
        path = ROOT / "openapi" / target
        contents = git(kaiten, "show", f"{commit}:{source}")
        changed = not path.exists() or path.read_text(encoding="utf-8") != contents
        path.write_text(contents, encoding="utf-8")
        print(f"{'updated' if changed else 'unchanged'} openapi/{target}")

    (ROOT / "openapi" / "source.yaml").write_text(
        SOURCE.format(ref=args.ref, commit=commit, today=date.today().isoformat()),
        encoding="utf-8",
    )
    print(f"synced from kaitencloud/kaiten@{commit[:10]} ({args.ref})")
    return 0


def git(checkout: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *arguments], check=True, capture_output=True, text=True
    ).stdout


if __name__ == "__main__":
    sys.exit(main())
