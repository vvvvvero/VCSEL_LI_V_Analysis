#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Threshold current extraction methods for VCSEL L-I-V analysis.

Implements multiple methods for extracting threshold current from optical power vs current data.

Author: Veronica GaoZhan
Date: February 2026
"""

import numpy as np


def smooth_ma(x: np.ndarray, window: int = 5) -> np.ndarray:
    """
    Uniform moving-average smoothing with edge-value padding.
    
    Parameters
    ----------
    x : np.ndarray
        Input array to smooth
    window : int
        Window size (must be >= 1)
    
    Returns
    -------
    np.ndarray
        Smoothed array
    """
    w = min(window, len(x))
    if w < 2:
        return x.copy()
    kernel = np.ones(w) / w
    pad = w // 2
    padded = np.pad(x, pad, mode="edge")
    out = np.convolve(padded, kernel, mode="valid")
    return out[: len(x)]


def threshold_linear_extrap(
    I: np.ndarray,
    P: np.ndarray,
    Iroll_A: float,
) -> tuple:
    """
    Threshold current by linear extrapolation.

    Fits a line to the clearly-lasing region (60–90 % of I_roll),
    extrapolates to P = 0.  Falls back to wider windows if needed.

    Parameters
    ----------
    I : np.ndarray
        Current array (A)
    P : np.ndarray
        Optical power array (W)
    Iroll_A : float
        Rollover current (A)

    Returns
    -------
    tuple
        (Ith_A, SE_WA) or (nan, nan) on failure.
    """
    for lo, hi in [(0.60, 0.90), (0.50, 0.95), (0.40, 0.98)]:
        mask = (I >= lo * Iroll_A) & (I <= hi * Iroll_A)
        if mask.sum() >= 3:
            break
    else:
        return np.nan, np.nan

    c = np.polyfit(I[mask], P[mask], 1)
    SE = float(c[0])
    b  = float(c[1])

    if SE <= 0.0:
        return np.nan, np.nan

    Ith = -b / SE
    if not (0.0 <= Ith < Iroll_A):
        return np.nan, SE           # return SE even if Ith out of range

    return float(Ith), float(SE)


def threshold_adaptive_kink(
    I: np.ndarray,
    P: np.ndarray,
    Iroll_A: float,
) -> tuple:
    """
    Threshold current by adaptive local-kink fitting.

    The legacy global fits can be pulled away from the real turn-on point by
    late rollover, compliance-limited points, or a long quasi-linear lasing
    region. This routine instead:

      1. smooths P(I) and its first / second derivatives,
      2. finds the first sustained slope increase above the low-current floor,
      3. refines that onset with the strongest nearby curvature,
      4. fits short linear windows on each side of the kink.

    Parameters
    ----------
    I : np.ndarray
        Current array (A)
    P : np.ndarray
        Optical power array (W)
    Iroll_A : float
        Rollover current (A)

    Returns
    -------
    tuple
        (Ith_A, SE_WA) or (nan, nan) on failure.
    """
    in_range = (I >= 0.0) & (I <= Iroll_A) & np.isfinite(P)
    I_r = I[in_range]
    P_r = P[in_range]
    if len(I_r) < 7:
        return np.nan, np.nan

    order = np.argsort(I_r)
    I_r = I_r[order]
    P_r = P_r[order]

    P_sm = smooth_ma(P_r, window=5)
    d1 = smooth_ma(np.gradient(P_sm, I_r), window=3)
    d2 = smooth_ma(np.gradient(d1, I_r), window=3)

    n_pts = len(I_r)
    n_base = max(3, min(5, n_pts // 6))
    P_base = float(np.median(P_sm[:n_base]))
    base_noise = float(np.median(np.abs(P_sm[:n_base] - P_base)))

    slope_pool = d1[n_base:]
    slope_pool = slope_pool[np.isfinite(slope_pool)]
    if len(slope_pool) < 3:
        return np.nan, np.nan

    k = max(3, len(slope_pool) // 5)
    target_slope = float(np.median(np.sort(slope_pool)[-k:]))
    if target_slope <= 0.0:
        return np.nan, np.nan

    slope_thresh = 0.25 * target_slope
    power_thresh = P_base + max(
        4.0 * base_noise,
        0.01 * max(float(np.nanmax(P_sm) - P_base), 0.0),
    )

    onset_idx = None
    for idx in range(n_base - 1, n_pts - 2):
        if (np.all(d1[idx:idx + 2] >= slope_thresh)
                and np.any(P_sm[idx:idx + 2] >= power_thresh)):
            onset_idx = idx
            break
    if onset_idx is None:
        return np.nan, np.nan

    lo = max(1, onset_idx - 2)
    hi = min(n_pts - 3, onset_idx + 2)
    if hi >= lo:
        seed_idx = lo + int(np.argmax(d2[lo:hi + 1]))
    else:
        seed_idx = onset_idx

    sub_end = min(seed_idx + 1, n_pts)
    sub_start = max(0, sub_end - 4)
    if sub_end - sub_start < 3:
        return np.nan, np.nan

    above_start = max(seed_idx + 1, onset_idx)
    while above_start < n_pts - 1 and d1[above_start] < 0.60 * target_slope:
        above_start += 1
    if above_start > n_pts - 3:
        return np.nan, np.nan

    above_end = min(n_pts, above_start + 5)
    while (above_end < n_pts
           and d1[above_end - 1] >= 0.50 * target_slope
           and above_end - above_start < 8):
        above_end += 1
    if above_end - above_start < 3:
        above_end = min(n_pts, above_start + 3)
    if above_end - above_start < 3:
        return np.nan, np.nan

    I_sub = I_r[sub_start:sub_end]
    P_sub = P_sm[sub_start:sub_end]
    I_above = I_r[above_start:above_end]
    P_above = P_sm[above_start:above_end]

    try:
        c_sub = np.polyfit(I_sub, P_sub, 1)
        c_above = np.polyfit(I_above, P_above, 1)
    except (np.linalg.LinAlgError, ValueError):
        return np.nan, np.nan

    se_sub = float(c_sub[0])
    se_above = float(c_above[0])
    if se_above <= 0.0:
        return np.nan, np.nan

    dslope = se_above - se_sub
    if dslope > 0.0:
        Ith = (c_sub[1] - c_above[1]) / dslope
    else:
        Ith = (P_base - c_above[1]) / se_above

    if not (0.0 <= Ith < Iroll_A):
        Ith = (P_base - c_above[1]) / se_above
    if not (0.0 <= Ith < Iroll_A):
        return np.nan, np.nan

    return float(Ith), float(se_above)


def threshold_two_segment(
    I: np.ndarray,
    P: np.ndarray,
    Iroll_A: float,
) -> tuple:
    """
    Threshold current by the two-segment (piecewise linear / kink) method.

    Scans all candidate breakpoints in the physically meaningful range
    (5 – 70 % of I_roll).  For each breakpoint it fits:
      - Segment 1: sub-threshold region (spontaneous emission floor)
      - Segment 2: above-threshold lasing region (up to 95 % of I_roll)
    The breakpoint that minimises the total squared residual is chosen.
    I_th is the intersection of the two best-fit lines; SE is the slope
    of the above-threshold segment.

    Parameters
    ----------
    I : np.ndarray
        Current array (A)
    P : np.ndarray
        Optical power array (W)
    Iroll_A : float
        Rollover current (A)

    Returns
    -------
    tuple
        (Ith_A, SE_WA) or (nan, nan) on failure.
    """
    in_range = (I >= 0.0) & (I <= 0.95 * Iroll_A) & np.isfinite(P)
    I_r = I[in_range]
    P_r = P[in_range]
    n_r = len(I_r)
    if n_r < 6:
        return np.nan, np.nan

    i_lo = max(int(np.searchsorted(I_r, 0.05 * Iroll_A)), 3)
    i_hi = min(int(np.searchsorted(I_r, 0.70 * Iroll_A)), n_r - 3)
    if i_lo >= i_hi:
        return np.nan, np.nan

    best_ith = np.nan
    best_se  = np.nan
    best_err = np.inf

    for split in range(i_lo, i_hi):
        I_sub   = I_r[:split]
        P_sub   = P_r[:split]
        I_above = I_r[split:]
        P_above = P_r[split:]

        try:
            c1 = np.polyfit(I_sub,   P_sub,   1)
            c2 = np.polyfit(I_above, P_above, 1)
        except (np.linalg.LinAlgError, ValueError):
            continue

        se_above = float(c2[0])
        se_sub   = float(c1[0])

        if se_above <= se_sub or se_above <= 0.0:
            continue

        dslope = se_above - se_sub
        Ith = (c1[1] - c2[1]) / dslope
        if not (0.0 <= Ith < Iroll_A):
            continue

        err = (float(np.sum((P_sub   - np.polyval(c1, I_sub  )) ** 2)) +
               float(np.sum((P_above - np.polyval(c2, I_above)) ** 2)))

        if err < best_err:
            best_err = err
            best_ith = Ith
            best_se  = se_above

    if not np.isfinite(best_ith):
        return np.nan, np.nan
    return float(best_ith), float(best_se)
