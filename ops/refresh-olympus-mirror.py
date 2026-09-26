#!/usr/bin/env python3
"""Materialize a redacted, hosted-agent-safe Olympus mirror.

This exists for macOS launchd deployments where the bot process cannot read a
checkout under Downloads. It copies only the same allowlisted text source and
documentation that the hosted snapshot accepts, redacting secret-shaped lines
before they ever reach the bot runtime directory.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
import shutil
import sys
import tempfile

# The script is executed from ``ops/`` but imports the shared repository
# filtering/redaction policy from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_investigator import _redacted_source, _snapshot_files

# Written inside the mirror on every successful build. bot.py reads this at
# startup to log how stale the mirror is — the mirror is a point-in-time copy
# and nothing currently refreshes it automatically, so a silent staleness of
# days or weeks is otherwise invisible to an operator.
_MARKER_NAME = ".olympus-mirror-refreshed-at"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing Olympus checkout")
    parser.add_argument("destination", type=Path, help="New runtime mirror directory")
    parser.add_argument(
        "--force", action="store_true",
        help="Replace an existing destination mirror instead of refusing to run.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        source = args.source.expanduser().resolve(strict=True)
    except OSError:
        print("Source checkout is not readable.", file=sys.stderr)
        return 2
    if not source.is_dir():
        print("Source checkout is not a directory.", file=sys.stderr)
        return 2

    destination = args.destination.expanduser()
    if destination.exists() and not args.force:
        print(
            "Destination already exists; refusing to overwrite it. "
            "Pass --force to replace it (for example, after updating Olympus).",
            file=sys.stderr,
        )
        return 2
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="olympus-mirror-", dir=destination.parent))
    displaced = destination.with_name(destination.name + ".prev-{}".format(os.getpid()))
    files_written = 0
    try:
        for path in _snapshot_files(source):
            relative = path.relative_to(source)
            target = temporary / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_text(_redacted_source(path), encoding="utf-8")
            os.chmod(target, 0o600)
            files_written += 1
        if not files_written:
            print("Source checkout produced no allowlisted files.", file=sys.stderr)
            return 2
        (temporary / _MARKER_NAME).write_text(str(int(time.time())), encoding="utf-8")
        os.chmod(temporary / _MARKER_NAME, 0o600)
        os.chmod(temporary, 0o700)
        if destination.exists():
            # Two renames rather than one: POSIX rename-onto-directory only
            # works when the target is empty, so the previous mirror is
            # first moved aside (still atomic, still on the same volume) and
            # only removed once the new mirror is safely in place. This
            # keeps --force idempotent and never leaves the runtime pointed
            # at a half-written directory.
            os.replace(destination, displaced)
        temporary.replace(destination)
        print("Created redacted Olympus mirror: files={}".format(files_written))
        return 0
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if displaced.exists():
            shutil.rmtree(displaced, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
