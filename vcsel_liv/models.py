#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data models and constants for VCSEL L-I-V analysis.

Author: Veronica GaoZhan
Date: February 2026
"""

import numpy as np

#: Minimum peak optical power (W) for a site to be classified as "lasing".
LASING_PMAX_THRESHOLD_W: float = 10e-6

#: Per-parameter display metadata: colormap, axis label, optional fixed bounds.
PARAM_META: dict = {
    "Ith_mA":     dict(label="Threshold current (mA)",  cmap="plasma_r"),
    "SE_WAA":     dict(label="Slope efficiency (W/A)",  cmap="viridis"),
    "Vth_V":      dict(label="Threshold voltage (V)",   cmap="RdYlGn_r"),
    "Pmax_mW":    dict(label="Peak power (mW)",         cmap="hot",      vmin=0),
    "Iroll_mA":   dict(label="Rollover current (mA)",   cmap="coolwarm"),
    "Vroll_V":    dict(label="Rollover voltage (V)",     cmap="coolwarm"),
    "Rs_ohm":     dict(label="Series resistance (Ω)",   cmap="RdYlGn_r"),
    "WPEmax_pct": dict(label="Peak WPE (%)",            cmap="viridis",  vmin=0),
    "Lasing":     dict(label="Lasing (1=yes / 0=no)",   cmap="RdYlGn",   vmin=0, vmax=1),
}


def create_empty_result() -> dict:
    """Create an empty result dictionary with all parameters initialized to NaN."""
    result: dict = {k: np.nan for k in PARAM_META}
    result["Lasing"] = 0
    result["Ith_mA"] = np.nan
    result["SE_WAA"] = np.nan
    result["Vth_V"] = np.nan
    result["Pmax_mW"] = np.nan
    result["Iroll_mA"] = np.nan
    result["Vroll_V"] = np.nan
    result["Rs_ohm"] = np.nan
    result["WPEmax_pct"] = np.nan
    result["Row"] = 0
    result["Column"] = 0
    result["Site"] = 0
    result["Filename"] = ""
    return result
