"""Features for one 10 s pre-alarm window at 125 Hz (ECG mV, PPG a.u., optional ABP mmHg).

Every feature is a float; NaN means "could not be measured" (the trees route NaN
explicitly). Nothing here fills a missing signal with zeros for the model: gaps are
interpolated only to run filters, and statistics are taken on observed samples.
The same function is used for training (on LinuxONE) and live inference (brain M2).
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt, welch

from . import ALARM_TYPES, FS

N = FS * 10
_SOS = {}
NAN = float('nan')


def _sos(lo, hi, order=2):
    key = (lo, hi, order)
    if key not in _SOS:
        if lo is None:
            _SOS[key] = butter(order, hi, 'lowpass', fs=FS, output='sos')
        elif hi is None:
            _SOS[key] = butter(order, lo, 'highpass', fs=FS, output='sos')
        else:
            _SOS[key] = butter(order, [lo, hi], 'bandpass', fs=FS, output='sos')
    return _SOS[key]


def as_signal(values):
    """List/array with None or NaN for missing -> float64 array (or None if absent)."""
    if values is None:
        return None
    x = np.array([np.nan if v is None else v for v in values], dtype=np.float64)
    return x if x.size else None


def _fill(x):
    ok = np.isfinite(x)
    if ok.all():
        return x.copy(), ok
    if ok.sum() < 2:
        return np.zeros_like(x), ok
    i = np.arange(x.size)
    y = x.copy()
    y[~ok] = np.interp(i[~ok], i[ok], x[ok])
    return y, ok


def _flat_fraction(x, ok, min_len=FS // 4):
    """Fraction of observed samples inside runs of (near) constant value >= 0.25 s."""
    if ok.sum() < 2:
        return NAN
    d = np.abs(np.diff(x))
    scale = np.nanpercentile(np.abs(x[ok] - np.nanmedian(x[ok])), 90) + 1e-12
    same = np.concatenate(([False], (d <= scale * 1e-3) & ok[1:] & ok[:-1]))
    run = np.cumsum(~same)
    counts = np.bincount(run)
    flat = (counts[run] >= min_len) & ok
    return float(flat.sum() / ok.sum())


def _quality(prefix, x):
    f = {}
    ok = np.isfinite(x)
    f[prefix + 'valid'] = float(ok.mean())
    if ok.sum() < FS:
        for k in ('std', 'ptp', 'flat', 'sat', 'hf', 'lf', 'mains'):
            f[prefix + k] = NAN
        return f
    y = x[ok]
    f[prefix + 'std'] = float(np.std(y))
    f[prefix + 'ptp'] = float(np.percentile(y, 99) - np.percentile(y, 1))
    f[prefix + 'flat'] = _flat_fraction(x, ok)
    f[prefix + 'sat'] = float(np.mean((y >= y.max()) | (y <= y.min())))
    z, _ = _fill(x)
    z = z - np.mean(z)
    p = np.abs(np.fft.rfft(z)) ** 2
    fr = np.fft.rfftfreq(z.size, 1 / FS)
    tot = p[fr > 0].sum() + 1e-12
    f[prefix + 'hf'] = float(p[fr > 30].sum() / tot)
    f[prefix + 'lf'] = float(p[(fr > 0) & (fr < 0.7)].sum() / tot)
    f[prefix + 'mains'] = float(p[((fr >= 48) & (fr <= 52)) | ((fr >= 58) & (fr <= 62))].sum() / tot)
    return f


def _gaps(times, start, stop):
    """Longest interval without a beat, edges included (s)."""
    edges = np.concatenate(([start], np.sort(times), [stop]))
    return float(np.max(np.diff(edges)))


def _rr_stats(prefix, t, f, span=(0.0, 10.0)):
    rr = np.diff(t)
    f[prefix + 'n'] = float(t.size)
    f[prefix + 'maxgap'] = _gaps(t, *span)
    if rr.size >= 1:
        f[prefix + 'hr'] = float(60 / np.median(rr))
        f[prefix + 'hrmin'] = float(60 / np.max(rr))
        k = min(4, rr.size)
        roll = np.convolve(rr, np.ones(k) / k, 'valid')
        f[prefix + 'hrmax4'] = float(60 / np.min(roll))
        f[prefix + 'hrmin4'] = float(60 / np.max(roll))
    else:
        for k in ('hr', 'hrmin', 'hrmax4', 'hrmin4'):
            f[prefix + k] = NAN
    if rr.size >= 2:
        f[prefix + 'rrcv'] = float(np.std(rr) / np.mean(rr))
        f[prefix + 'rmssd'] = float(np.sqrt(np.mean(np.diff(rr) ** 2)) / np.mean(rr))
    else:
        f[prefix + 'rrcv'] = f[prefix + 'rmssd'] = NAN


def detect_qrs(x):
    """Energy-based QRS detector for 125 Hz ECG. Returns (sample indices, bandpassed, valid mask)."""
    z, ok = _fill(x)
    if ok.sum() < 2 * FS:
        return np.zeros(0, int), None, ok
    b = sosfiltfilt(_sos(5, 20), z)
    b[~ok] = 0.0
    e = np.concatenate(([0.0], np.diff(b) ** 2))
    w = int(0.12 * FS)
    integ = np.convolve(e, np.ones(w) / w, 'same')
    # Robust reference: a single artefact spike must not hide every real beat, so the
    # global 98th percentile is capped at 2.5x the median of the five 2 s segment maxima.
    segmax = np.array([integ[i:i + 2 * FS].max() for i in range(0, integ.size, 2 * FS)])
    ref = min(np.percentile(integ[ok], 98), 2.5 * np.median(segmax))
    if ref <= 1e-7:
        return np.zeros(0, int), b, ok
    peaks, _ = find_peaks(integ, height=0.25 * ref, distance=int(0.2 * FS))
    # Second pass: drop peaks far below their neighbours (T waves, noise), keep VT/VF peaks.
    if peaks.size >= 3:
        h = integ[peaks]
        med = np.median(h)
        peaks = peaks[h >= 0.2 * med]
    r = []
    for p in peaks:
        a, c = max(0, p - 10), min(x.size, p + 10)
        r.append(a + int(np.argmax(np.abs(b[a:c]))))
    r = np.unique(np.array(r, dtype=int))
    if r.size >= 2:  # enforce refractory after refinement
        keep = [r[0]]
        for v in r[1:]:
            if v - keep[-1] >= int(0.2 * FS):
                keep.append(v)
        r = np.array(keep, dtype=int)
    return r, b, ok


def _ecg_features(prefix, x, full=True):
    f = _quality(prefix, x)
    r, b, ok = detect_qrs(x)
    t = r / FS
    _rr_stats(prefix, t, f)
    last = t[t >= 5.0]
    f[prefix + 'n_last5'] = float(last.size)
    f[prefix + 'maxgap_last5'] = _gaps(last, 5.0, 10.0)
    f[prefix + 'hr_last5'] = float(60 / np.median(np.diff(last))) if last.size >= 2 else NAN
    if b is not None:
        # Detector-free rate: autocorrelation of the QRS energy envelope (0.24-2 s lags).
        v = np.concatenate(([0.0], np.diff(b) ** 2))
        v = v - v.mean()
        ac = np.correlate(v, v, 'full')[v.size - 1:]
        ac = ac / (ac[0] + 1e-12)
        lo, hi = int(0.24 * FS), int(2.0 * FS)
        k = lo + int(np.argmax(ac[lo:hi]))
        f[prefix + 'acf'], f[prefix + 'acf_hr'] = float(ac[k]), float(60 * FS / k)
    else:
        f[prefix + 'acf'] = f[prefix + 'acf_hr'] = NAN
    keys = ('qrsw', 'tmplcorr', 'ampcv', 'kurt', 'skew', 'tci', 'zcr', 'domf', 'vfband', 'conc',
            'sent', 'vfband_last4', 'domf_last4', 'conc_last4', 'kurt_last4', 'tci_last4')
    if b is None:
        for k in keys:
            f[prefix + k] = NAN
        return f
    a = np.abs(b)
    widths, amps = [], []
    for p in r:
        pk = a[p]
        if pk <= 0:
            continue
        lo = p
        while lo > 0 and a[lo] > 0.5 * pk and p - lo < 30:
            lo -= 1
        hi = p
        while hi < a.size - 1 and a[hi] > 0.5 * pk and hi - p < 30:
            hi += 1
        widths.append((hi - lo) * 1000 / FS)
        amps.append(pk)
    f[prefix + 'qrsw'] = float(np.median(widths)) if widths else NAN
    f[prefix + 'ampcv'] = float(np.std(amps) / (np.mean(amps) + 1e-12)) if len(amps) >= 2 else NAN
    z, _ = _fill(x)
    y = sosfiltfilt(_sos(0.5, 40), z)
    y[~ok] = np.nan
    seg = int(0.3 * FS)
    beats = [y[p - seg:p + seg] for p in r if p - seg >= 0 and p + seg <= y.size and np.isfinite(y[p - seg:p + seg]).all()]
    if len(beats) >= 3:
        B = np.array(beats)
        tmpl = np.median(B, axis=0)
        cs = [np.corrcoef(v, tmpl)[0, 1] for v in B if np.std(v) > 0]
        f[prefix + 'tmplcorr'] = float(np.mean(cs)) if cs else NAN
    else:
        f[prefix + 'tmplcorr'] = NAN

    def morph(v):
        v = v[np.isfinite(v)]
        if v.size < FS:
            return NAN, NAN, NAN, NAN
        v = v - np.mean(v)
        s = np.std(v) + 1e-12
        kurt = float(np.mean(v ** 4) / s ** 4)
        skew = float(np.mean(v ** 3) / s ** 3)
        tci = float(np.mean(np.abs(v) > 0.2 * np.max(np.abs(v))))
        zcr = float(np.mean(np.diff(np.sign(v)) != 0) * FS)
        return kurt, skew, tci, zcr

    f[prefix + 'kurt'], f[prefix + 'skew'], f[prefix + 'tci'], f[prefix + 'zcr'] = morph(y)
    f[prefix + 'kurt_last4'], _, f[prefix + 'tci_last4'], _ = morph(y[-4 * FS:])

    def spectral(v, nper):
        v = v[np.isfinite(v)]
        if v.size < nper:
            return NAN, NAN, NAN, NAN
        fr, p = welch(v - np.mean(v), fs=FS, nperseg=nper)
        band = (fr >= 0.5) & (fr <= 30)
        tot = p[band].sum() + 1e-12
        sel = (fr >= 0.5) & (fr <= 15)
        dom = float(fr[sel][np.argmax(p[sel])])
        vf = float(p[(fr >= 2) & (fr <= 8)].sum() / tot)
        conc = float(p[band & (np.abs(fr - dom) <= 0.6)].sum() / tot)
        q = p[band] / tot
        sent = float(-np.sum(q * np.log(q + 1e-12)) / np.log(q.size))
        return dom, vf, conc, sent

    f[prefix + 'domf'], f[prefix + 'vfband'], f[prefix + 'conc'], f[prefix + 'sent'] = spectral(y, 512)
    f[prefix + 'domf_last4'], f[prefix + 'vfband_last4'], f[prefix + 'conc_last4'], _ = spectral(y[-4 * FS:], 256)
    return f


def detect_pulses(x):
    z, ok = _fill(x)
    if ok.sum() < 2 * FS:
        return np.zeros(0, int), None, ok
    y = sosfiltfilt(_sos(0.5, 8), z)
    y[~ok] = np.nan
    obs = y[ok]
    spread = np.percentile(obs, 95) - np.percentile(obs, 5)
    if spread <= 0:
        return np.zeros(0, int), y, ok
    peaks, _ = find_peaks(np.nan_to_num(y, nan=np.nanmin(obs)), prominence=0.3 * spread, distance=int(0.27 * FS))
    return peaks, y, ok


def _pulse_features(prefix, x, pressure=False):
    f = _quality(prefix, x)
    p, y, ok = detect_pulses(x)
    t = p / FS
    _rr_stats(prefix, t, f)
    keys = ('acf', 'acf_hr', 'amp_ratio_last3', 'amp_rel')
    if pressure:
        keys += ('mean', 'sys', 'dia', 'pp', 'mean_last3', 'min2s')
    if y is None:
        for k in keys:
            f[prefix + k] = NAN
        return f
    v = np.nan_to_num(y - np.nanmean(y))
    ac = np.correlate(v, v, 'full')[v.size - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = int(0.27 * FS), int(2.0 * FS)
    k = lo + int(np.argmax(ac[lo:hi]))
    f[prefix + 'acf'] = float(ac[k])
    f[prefix + 'acf_hr'] = float(60 * FS / k)
    sp = lambda s: (np.nanpercentile(s, 95) - np.nanpercentile(s, 5)) if np.isfinite(s).sum() > FS // 2 else NAN
    first, last = sp(y[:7 * FS]), sp(y[-3 * FS:])
    f[prefix + 'amp_ratio_last3'] = float(last / first) if first and np.isfinite(first) and first > 0 else NAN
    f[prefix + 'amp_rel'] = float(sp(y) / (np.nanstd(x) + 1e-12))
    if pressure:
        obs = x[np.isfinite(x)]
        f[prefix + 'mean'] = float(np.mean(obs)) if obs.size else NAN
        pk = x[p] if p.size else np.array([])
        pk = pk[np.isfinite(pk)]
        f[prefix + 'sys'] = float(np.median(pk)) if pk.size else NAN
        troughs = [np.nanmin(x[a:b]) for a, b in zip(p[:-1], p[1:]) if np.isfinite(x[a:b]).any()]
        f[prefix + 'dia'] = float(np.median(troughs)) if troughs else NAN
        f[prefix + 'pp'] = f[prefix + 'sys'] - f[prefix + 'dia']
        l3 = x[-3 * FS:]
        f[prefix + 'mean_last3'] = float(np.nanmean(l3)) if np.isfinite(l3).any() else NAN
        m2 = [np.nanmean(x[i:i + 2 * FS]) for i in range(0, N - 2 * FS + 1, FS // 2) if np.isfinite(x[i:i + 2 * FS]).mean() > .5]
        f[prefix + 'min2s'] = float(np.min(m2)) if m2 else NAN
    return f


def _absent(prefix, pressure=False):
    proto = _pulse_features(prefix, np.full(N, np.nan), pressure)
    return {k: NAN for k in proto}


def window_features(ecg, ppg=None, abp=None, alarm_code=None, ecg2=None):
    """Feature dict for one window. Inputs: 1250 samples each (None/NaN = missing)."""
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        return _window_features(ecg, ppg, abp, alarm_code, ecg2)


def _window_features(ecg, ppg, abp, alarm_code, ecg2):
    ecg, ppg, abp, ecg2 = (as_signal(v) for v in (ecg, ppg, abp, ecg2))
    for name, v in (('ecg', ecg), ('ppg', ppg), ('abp', abp), ('ecg2', ecg2)):
        if v is not None and v.size != N:
            raise ValueError(f'{name} must have {N} samples, got {v.size}')
    f = {f'alarm_{a}': float(alarm_code == a) for a in ALARM_TYPES}
    f.update(_ecg_features('ecg_', ecg if ecg is not None else np.full(N, np.nan)))
    if ecg2 is not None:
        f.update(_ecg_features('ecg2_', ecg2))
    f.update(_pulse_features('ppg_', ppg) if ppg is not None else _absent('ppg_'))
    f.update(_pulse_features('abp_', abp, pressure=True) if abp is not None else _absent('abp_', True))
    # Agreement between the electrical heartbeat and the mechanical pulse(s).
    for src in ('ppg', 'abp'):
        e, q = f['ecg_hr'], f[src + '_hr']
        usable = f[src + '_valid'] > .8 if np.isfinite(f[src + '_valid']) else False
        f[f'agree_{src}_dhr'] = float(e - q) if usable and np.isfinite(e) and np.isfinite(q) else NAN
        f[f'agree_{src}_ratio'] = float(e / q) if usable and np.isfinite(e) and np.isfinite(q) and q > 0 else NAN
        f[f'agree_{src}_dgap'] = float(f['ecg_maxgap'] - f[src + '_maxgap']) if usable and np.isfinite(f['ecg_maxgap']) else NAN
    gaps = [f[s + '_maxgap'] for s in ('ppg', 'abp') if np.isfinite(f[s + '_valid']) and f[s + '_valid'] > .8]
    f['pulse_minmaxgap'] = float(min(gaps)) if gaps else NAN
    hrs = [f[s + '_hr'] for s in ('ppg', 'abp') if np.isfinite(f[s + '_valid']) and f[s + '_valid'] > .8 and np.isfinite(f[s + '_hr'])]
    f['pulse_hr_best'] = float(np.median(hrs)) if hrs else NAN
    f['n_pulse_channels'] = float(len(gaps))
    return f


def feature_names(two_lead=False):
    z = np.zeros(N)
    return list(window_features(z, z, z, 'VTACH', z if two_lead else None).keys())


def vector(feats, names):
    return np.array([feats.get(k, NAN) for k in names], dtype=np.float64)
