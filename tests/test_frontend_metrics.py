"""Tests for frontend_metrics time normalization (systemd CST -> ISO +08:00)."""
from __future__ import annotations

from memorycore.frontend_metrics import _parse_systemd_ts


class TestParseSystemdTs:
    def test_cst_wall_clock_to_iso(self):
        assert _parse_systemd_ts("Wed 2026-08-26 15:16:17 CST") == "2026-08-26T15:16:17+08:00"

    def test_next_trigger_to_iso(self):
        assert _parse_systemd_ts("Thu 2026-08-27 03:09:48 CST") == "2026-08-27T03:09:48+08:00"

    def test_iso_passthrough(self):
        assert _parse_systemd_ts("2026-08-26T15:16:17+08:00") == "2026-08-26T15:16:17+08:00"

    def test_empty_passthrough(self):
        assert _parse_systemd_ts("") == ""

    def test_unparseable_passthrough(self):
        assert _parse_systemd_ts("n/a") == "n/a"