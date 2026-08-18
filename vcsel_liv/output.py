#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Output and reporting utilities for VCSEL L-I-V analysis.

Author: Veronica GaoZhan
Date: February 2026
"""

import csv
from pathlib import Path

import numpy as np


def write_summary_csv(records: list, output_path: Path) -> None:
    """
    Write extracted parameters to a CSV file, sorted by (Row, Column).
    
    Parameters
    ----------
    records : list
        List of result dictionaries
    output_path : Path
        Output CSV file path
    """
    fieldnames = [
        "Site", "Row", "Column", "Filename",
        "Ith_mA", "SE_WAA", "Vth_V", "Pmax_mW",
        "Iroll_mA", "Vroll_V", "Rs_ohm", "WPEmax_pct", "Lasing",
    ]
    sorted_records = sorted(records, key=lambda r: (r["Row"], r["Column"]))

    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in sorted_records:
            row_out = {}
            for k in fieldnames:
                v = rec.get(k, "")
                if isinstance(v, float):
                    row_out[k] = f"{v:.5g}" if np.isfinite(v) else ""
                else:
                    row_out[k] = v
            writer.writerow(row_out)


def print_statistics(records: list) -> None:
    """
    Print mean / std / min / max for each extracted parameter.
    
    Parameters
    ----------
    records : list
        List of result dictionaries
    """
    from . import models

    params = [k for k in models.PARAM_META if k != "Lasing"]
    width  = 62
    print("\n" + "=" * width)
    print(f"{'Parameter':<16} {'N':>4} {'Mean':>10} {'Std':>10} "
          f"{'Min':>10} {'Max':>10}")
    print("-" * width)
    for p in params:
        vals = [r[p] for r in records if np.isfinite(r.get(p, np.nan))]
        if vals:
            a = np.array(vals)
            print(f"{p:<16} {len(a):>4} {np.mean(a):>10.3g} "
                  f"{np.std(a):>10.3g} {np.min(a):>10.3g} {np.max(a):>10.3g}")
        else:
            print(f"{p:<16} {'–':>4}")
    lasing = sum(1 for r in records if r.get("Lasing", 0) == 1)
    total  = len(records)
    print("-" * width)
    print(f"Yield: {lasing}/{total} sites lasing  "
          f"({100 * lasing / max(total, 1):.1f} %)")
    print("=" * width)
