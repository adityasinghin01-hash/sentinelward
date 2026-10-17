"""Acceptance checks 1, 2, 3 and 5: resampling, gaps, heart rate, cuff readings."""
from __future__ import annotations

import numpy as np
import pytest

from conftest import spike_ecg
from sw_data.beats import hr_from_ecg
from sw_data.dsp import (cuff_readings, ecg_to_mv, flat_mask, pct_flat, resample_to_125, to_second_grid,
                         window_resample)


# ---------------------------------------------------------------- check 1


def test_sine_250_to_125_keeps_amplitude_and_length() -> None:
    fs, secs = 250, 330
    t = np.arange(secs * fs) / fs
    x = np.sin(2 * np.pi * 5.0 * t)
    y = window_resample(x, fs, 0, x.size)
    assert y.size == secs * 125
    mid = y[125:-125]
    assert abs(np.max(np.abs(mid)) - 1.0) < 0.02
    # same phase: compare against the ideal 125 Hz sine
    ideal = np.sin(2 * np.pi * 5.0 * np.arange(y.size) / 125.0)
    assert np.max(np.abs(mid - ideal[125:-125])) < 0.02


def test_500_to_125_length_exact() -> None:
    x = np.sin(2 * np.pi * 3.0 * np.arange(60 * 500) / 500)
    assert resample_to_125(x, 500).size == 60 * 125


def test_125_passes_through_unchanged() -> None:
    x = np.random.default_rng(1).normal(size=1250)
    x[100:200] = np.nan
    y = resample_to_125(x, 125)
    np.testing.assert_array_equal(np.isnan(y), np.isnan(x))
    np.testing.assert_allclose(y[~np.isnan(y)], x[~np.isnan(x)])


# ---------------------------------------------------------------- check 2


@pytest.mark.parametrize("fs", [250, 500])
@pytest.mark.parametrize("gap_start", [5000, 5001, 5003])
def test_one_second_gap_grows_at_most_one_sample_each_side(fs: int, gap_start: int) -> None:
    d = fs // 125
    x = np.sin(2 * np.pi * 2.0 * np.arange(30 * fs) / fs)
    a, b = gap_start, gap_start + fs - 1          # 1 s missing, inclusive
    x[a:b + 1] = np.nan
    y = window_resample(x, fs, 0, x.size)
    assert y.size == 30 * 125
    nan_idx = np.flatnonzero(np.isnan(y))
    core = np.arange(-(-a // d), b // d + 1)      # outputs whose position k*d is inside the gap
    assert set(core) <= set(nan_idx), "gap must stay missing"
    assert nan_idx.min() >= core.min() - 1 and nan_idx.max() <= core.max() + 1, "gap grew by more than 1 sample"
    assert np.all(np.diff(nan_idx) == 1), "nothing outside the gap may become NaN"


def test_missing_sentinel_becomes_nan_not_zero() -> None:
    x = np.ones(2500)
    x[1000:1250] = -32768.0
    y = window_resample(x, 250, 0, x.size)
    assert np.isnan(y[520:600]).all()
    assert not np.any(y[np.isfinite(y)] == 0.0)


# ---------------------------------------------------------------- check 3


def test_hr_75_bpm_spike_train() -> None:
    fs, secs = 125, 60
    hr = hr_from_ecg(spike_ecg(secs * fs, fs, 75.0), fs, secs)
    valid = hr[5:]
    assert np.isfinite(valid).all()
    assert np.all(np.abs(valid - 75) <= 1)


def test_hr_flat_ecg_is_zero() -> None:
    fs, secs = 125, 30
    hr = hr_from_ecg(np.zeros(secs * fs), fs, secs)
    assert np.all(hr[5:] == 0)
    assert not np.any(hr[:4] == 0), "no 0 before 5 s of signal"


def test_hr_flat_noisy_ecg_is_zero() -> None:
    fs, secs = 125, 30
    x = np.random.default_rng(3).normal(0, 0.02, secs * fs)
    assert np.all(hr_from_ecg(x, fs, secs)[5:] == 0)


def test_hr_missing_ecg_is_nan() -> None:
    fs, secs = 125, 30
    hr = hr_from_ecg(np.full(secs * fs, np.nan), fs, secs)
    assert np.isnan(hr).all()


def test_hr_mostly_missing_window_is_nan_not_zero() -> None:
    fs, secs = 125, 40
    x = spike_ecg(secs * fs, fs, 75.0)
    x[20 * fs:30 * fs] = np.nan
    hr = hr_from_ecg(x, fs, secs)
    assert np.isnan(hr[22:29]).all()
    assert not np.any(hr == 0)


def test_hr_asystole_after_beats_goes_to_zero() -> None:
    fs, secs = 125, 40
    x = spike_ecg(secs * fs, fs, 75.0)
    x[20 * fs:] = 0.0
    hr = hr_from_ecg(x, fs, secs)
    assert np.all(np.abs(hr[6:19] - 75) <= 1)
    assert np.all(hr[26:] == 0)


# ---------------------------------------------------------------- check 5


def test_cuff_new_readings() -> None:
    sys_ = np.array([100, 100, 100, 112, 112, np.nan, 95], dtype=float)
    dia = np.array([60, 60, 60, 70, 70, np.nan, 55], dtype=float)
    mean = np.array([73, 73, 73, 84, 84, np.nan, 68], dtype=float)
    t = np.arange(7, dtype=float)
    rows = cuff_readings(t, sys_, dia, mean)
    assert rows.shape == (3, 4)
    np.testing.assert_array_equal(rows[0], [0, 100, 60, 73])
    after_first = rows[1:]
    assert after_first.shape[0] == 2
    np.testing.assert_array_equal(after_first[:, 0], [3, 6])
    np.testing.assert_array_equal(after_first[:, 1], [112, 95])
    np.testing.assert_array_equal(after_first[:, 2:], [[70, 84], [55, 68]])


def test_cuff_value_carried_into_window_is_not_new() -> None:
    t = np.arange(-3, 4, dtype=float)
    sys_ = np.array([100, 100, 100, 100, 112, 112, 112], dtype=float)
    rows = cuff_readings(t, sys_, sys_, sys_, duration_s=4)
    np.testing.assert_array_equal(rows[:, :2], [[1, 112]])


def test_cuff_empty_shape() -> None:
    rows = cuff_readings(np.arange(3.0), np.full(3, np.nan), np.full(3, np.nan), np.full(3, np.nan))
    assert rows.shape == (0, 4)


# ---------------------------------------------------------------- helpers


def test_second_grid_hold_under_two_seconds() -> None:
    t = np.arange(10, dtype=float)
    v = np.where(t % 2 == 0, 70.0, np.nan)
    v[4] = np.nan                                 # one 2 s sample lost
    g = to_second_grid(t, v, 10, 2.0)
    np.testing.assert_array_equal(np.isnan(g), [False, False, False, False, True, True,
                                                False, False, False, False])


def test_flat_mask_two_seconds() -> None:
    wiggle = np.sin(np.arange(1, 251))
    x = np.r_[wiggle, np.zeros(500), wiggle]
    assert flat_mask(x, 250).sum() == 500
    assert pct_flat(np.r_[np.zeros(400), wiggle, wiggle], 250) == 0.0  # 1.6 s is not flat


def test_ecg_units() -> None:
    x, note, warn = ecg_to_mv(np.array([1000.0]), "uV")
    assert x[0] == 1.0 and note and not warn
    _, note, warn = ecg_to_mv(np.array([1.0]), "")
    assert warn and "blank" in note
    _, note, warn = ecg_to_mv(np.array([1.0]), "mV")
    assert note is None and not warn
