#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  atomic_io.py
#     CREATED:  2026-09-20
# DESCRIPTION:  Crash-safe file writing shared by the on-disk cache and the
#               word-history log.
#
# =============================================================================

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so that readers never see a partial file.

    The bytes go to a temporary file in the destination directory first and
    are then moved over the target with ``os.replace``, which is atomic on
    both POSIX and Windows. Missing parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
