"""Unit tests for atomic_io.py."""

from __future__ import annotations

import os

import pytest

from dictionary_app import atomic_io


class TestAtomicWriteBytes:
    def test_writes_the_bytes(self, tmp_path):
        target = tmp_path / "out.bin"
        atomic_io.atomic_write_bytes(target, b"hello")
        assert target.read_bytes() == b"hello"

    def test_creates_missing_parent_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "out.bin"
        atomic_io.atomic_write_bytes(target, b"x")
        assert target.read_bytes() == b"x"

    def test_replaces_existing_content(self, tmp_path):
        target = tmp_path / "out.bin"
        target.write_bytes(b"old")
        atomic_io.atomic_write_bytes(target, b"new")
        assert target.read_bytes() == b"new"

    def test_leaves_no_temporary_files_behind(self, tmp_path):
        atomic_io.atomic_write_bytes(tmp_path / "out.bin", b"x")
        assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]

    def test_failure_keeps_the_original_and_cleans_up(self, tmp_path, monkeypatch):
        target = tmp_path / "out.bin"
        target.write_bytes(b"original")

        def boom(src, dst):
            raise OSError("disk on fire")

        monkeypatch.setattr(os, "replace", boom)

        with pytest.raises(OSError, match="disk on fire"):
            atomic_io.atomic_write_bytes(target, b"new")

        assert target.read_bytes() == b"original"
        assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]
