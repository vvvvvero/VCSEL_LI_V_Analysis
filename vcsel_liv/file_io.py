#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
File I/O utilities for VCSEL L-I-V analysis.

Handles loading per-site CSV files and parsing filenames.

Author: Veronica GaoZhan
Date: February 2026
"""

import csv
import re
from pathlib import Path
from typing import Optional

import numpy as np

_FILE_RE = re.compile(r"row_(\d+)_col_(\d+)_(?:2terminal_)?site_(\d+)", re.IGNORECASE)


def parse_filename(path: Path) -> Optional[tuple]:
    """
    Return (row, col, site) from a result CSV filename, or None.
    
    Expected format: row_XXX_col_YYY_site_ZZZ.csv or row_XXX_col_YYY_2terminal_site_ZZZ.csv
    """
    m = _FILE_RE.search(path.stem)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def load_site_csv(path: Path) -> Optional[dict]:
    """
    Load a per-site CSV into numpy arrays.

    Returns dict with keys ``'I'``, ``'V'``, ``'P'`` (all float64),
    or ``None`` if the file cannot be read / has missing columns.
    
    Expected CSV columns: Current_A, Voltage_V, Optical_Power_W
    """
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = [r for r in reader if r.get("Status", "OK").strip() == "OK"]
        if not rows:
            return None
        required = {"Current_A", "Voltage_V", "Optical_Power_W"}
        if not required.issubset(set(rows[0].keys())):
            return None
        I = np.array([float(r["Current_A"])       for r in rows], dtype=float)
        V = np.array([float(r["Voltage_V"])        for r in rows], dtype=float)
        P = np.array([float(r["Optical_Power_W"])  for r in rows], dtype=float)
        return {"I": I, "V": V, "P": P}
    except Exception:
        return None
