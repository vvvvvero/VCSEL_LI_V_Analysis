#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Parameter extraction for VCSEL L-I-V analysis.

Main entry point for extracting all LIV parameters from I-V-P data.

Author: Veronica GaoZhan
Date: February 2026
"""

import numpy as np

from . import models
from . import threshold_extraction as te


def extract_parameters(
    data: dict,
    ith_method: str = "adaptive_kink",
    lasing_threshold_uw: float = 10.0,
) -> dict:
    """
    Extract VCSEL LIV parameters from arrays I, V, P.

    Parameters
    ----------
    data : dict
        Dictionary with keys 'I', 'V', 'P' (numpy float64 arrays, same length)
    ith_method : str
        Threshold extraction method: ``'adaptive_kink'`` (default),
        ``'two_segment'``, or ``'linear_extrap'``
    lasing_threshold_uw : float
        Minimum peak optical power (µW) for device to be classified as lasing

    Returns
    -------
    dict
        Result dictionary with all extracted parameters and 'Lasing' flag
    """
    lasing_thresh_w = lasing_threshold_uw * 1e-6

    I = data["I"]
    V = data["V"]
    P = data["P"]

    result = models.create_empty_result()

    # ---------------------------------------------------------------
    # Peak power and rollover current
    # ---------------------------------------------------------------
    if len(I) < 2:
        return result

    P_valid = P[np.isfinite(P)]
    if len(P_valid) == 0:
        return result

    idx_roll = int(np.argmax(np.where(np.isfinite(P), P, -np.inf)))
    Pmax_W   = float(P[idx_roll])
    Iroll_A  = float(I[idx_roll])
    Vroll_V  = float(V[idx_roll])

    result["Pmax_mW"]  = Pmax_W  * 1e3
    result["Iroll_mA"] = Iroll_A * 1e3
    result["Vroll_V"]  = Vroll_V

    if Pmax_W < lasing_thresh_w or Iroll_A <= 0.0 or len(I) < 5:
        return result

    result["Lasing"] = 1

    # ---------------------------------------------------------------
    # Threshold current
    # ---------------------------------------------------------------
    P_sm     = te.smooth_ma(P, window=5)
    idx_sm   = int(np.argmax(P_sm))
    Iroll_sm = float(I[idx_sm]) if idx_sm > 0 else Iroll_A

    ith_fns = {
        "adaptive_kink": te.threshold_adaptive_kink,
        "two_segment": te.threshold_two_segment,
        "linear_extrap": te.threshold_linear_extrap,
    }
    _ith_fn = ith_fns.get(ith_method, te.threshold_adaptive_kink)

    Ith_A = np.nan
    SE_WA = np.nan
    for P_try, Iroll_try in ((P_sm, Iroll_sm), (P, Iroll_A)):
        Ith_A, SE_WA = _ith_fn(I, P_try, Iroll_try)
        if np.isfinite(Ith_A):
            break

    if not np.isfinite(Ith_A) and _ith_fn is te.threshold_adaptive_kink:
        for fallback_fn in (te.threshold_two_segment, te.threshold_linear_extrap):
            for P_try, Iroll_try in ((P_sm, Iroll_sm), (P, Iroll_A)):
                Ith_A, SE_WA = fallback_fn(I, P_try, Iroll_try)
                if np.isfinite(Ith_A):
                    break
            if np.isfinite(Ith_A):
                break

    if np.isfinite(Ith_A):
        result["Ith_mA"] = float(Ith_A * 1e3)
        result["SE_WAA"] = float(SE_WA)

        # Threshold voltage: interpolate V(Ith) from the forward-bias region
        fwd = (I > 0.0) & (V > 0.0)
        if fwd.sum() >= 2:
            result["Vth_V"] = float(np.interp(Ith_A, I[fwd], V[fwd]))

    # ---------------------------------------------------------------
    # Series resistance: linear fit to V-I above threshold
    # ---------------------------------------------------------------
    if np.isfinite(Ith_A):
        mask_rs = (I >= Ith_A) & (I <= Iroll_sm * 0.90) & (V > 0.5)
        if mask_rs.sum() >= 3:
            c_vi = np.polyfit(I[mask_rs], V[mask_rs], 1)
            result["Rs_ohm"] = float(c_vi[0])

    # ---------------------------------------------------------------
    # Wall-plug efficiency  WPE = P_opt / (V × I)
    # Require V > 1.5 V (forward-biased diode) and I above threshold
    # to avoid noise-dominated or invalid operating points.
    # ---------------------------------------------------------------
    ith_filter = Ith_A if np.isfinite(Ith_A) else (0.20 * Iroll_A)
    with np.errstate(divide="ignore", invalid="ignore"):
        Pin = V * I
        wpe = np.where(
            (Pin > 1e-12) & (I >= ith_filter) & (V > 1.5),
            P / Pin,
            0.0,
        )
    wpe_max = float(np.nanmax(wpe) * 100.0)
    # Physical cap: WPE > 100 % is not possible; flag as NaN for investigation
    result["WPEmax_pct"] = wpe_max if wpe_max <= 100.0 else np.nan

    return result
