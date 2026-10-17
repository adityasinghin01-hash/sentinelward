"""Tests for sw_common.clock."""

from __future__ import annotations

import time

import pytest

from sw_common import WINDOW_MS, now_ms, window_start_for


def test_now_ms_is_int_epoch_milliseconds():
    before = int(time.time() * 1000)
    value = now_ms()
    after = int(time.time() * 1000)
    assert type(value) is int
    assert before - 1 <= value <= after + 1


@pytest.mark.parametrize("ts,start", [
    (1792252795000, 1792252795000),
    (1792252799999, 1792252795000),
    (1792252800000, 1792252800000),
    (1792252800500, 1792252800000),
    (0, 0),
    (4999, 0),
    (-1, -5000),
])
def test_window_start_for(ts, start):
    assert window_start_for(ts) == start
    assert window_start_for(ts) % WINDOW_MS == 0


@pytest.mark.parametrize("bad", [1792252800000.0, "1792252800000", None, True])
def test_window_start_for_rejects_non_int(bad):
    with pytest.raises(TypeError, match="window_start_for"):
        window_start_for(bad)
