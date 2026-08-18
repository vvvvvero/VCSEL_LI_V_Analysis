#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main analysis pipeline for VCSEL L-I-V analysis.

Author: Veronica GaoZhan
Date: February 2026
"""

from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import file_io
from . import parameter_extractor
from . import visualization
from . import output


def run_analysis(
    results_folder: Path,
    output_folder: Path,
    lasing_threshold_uw: float = 10.0,
    generate_liv_curves: bool = True,
    ith_method: str = "adaptive_kink",
    progress_cb: Optional[Callable] = None,
) -> list:
    """
    Full analysis pipeline.

    Parameters
    ----------
    results_folder : Path
        Directory with per-site CSV files
    output_folder : Path
        Where to write all outputs
    lasing_threshold_uw : float
        Minimum Pmax (µW) to classify a device as lasing (default: 10.0)
    generate_liv_curves : bool
        If True, write per-site L-I-V PNG files (default: True)
    ith_method : str
        Threshold extraction method: ``'adaptive_kink'`` (default),
        ``'two_segment'``, or ``'linear_extrap'``
    progress_cb : callable, optional
        Optional callable(current, total, message) for progress updates

    Returns
    -------
    list
        Per-site parameter records
    
    Raises
    ------
    FileNotFoundError
        If no CSV files found in results_folder
    RuntimeError
        If no valid site files could be processed
    """
    wafer_map_dir = output_folder / "wafer_maps"
    liv_curve_dir = output_folder / "liv_curves"

    output_folder.mkdir(parents=True, exist_ok=True)
    wafer_map_dir.mkdir(exist_ok=True)
    if generate_liv_curves:
        liv_curve_dir.mkdir(exist_ok=True)

    csv_files = sorted(results_folder.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found in:\n  {results_folder}\n"
            "Please check that the correct results folder is selected."
        )

    records: list = []
    max_row = max_col = 0
    total = len(csv_files)
    n_skip_name = 0
    n_skip_load = 0

    for i, csv_path in enumerate(csv_files):
        parsed = file_io.parse_filename(csv_path)
        if parsed is None:
            n_skip_name += 1
            msg = f"Skipped (unrecognised filename): {csv_path.name}"
            if progress_cb:
                progress_cb(i + 1, total, msg)
            continue

        row, col, site = parsed
        max_row = max(max_row, row)
        max_col = max(max_col, col)

        data = file_io.load_site_csv(csv_path)
        if data is None:
            n_skip_load += 1
            msg = f"Skipped (load error): {csv_path.name}"
            if progress_cb:
                progress_cb(i + 1, total, msg)
            continue

        params = parameter_extractor.extract_parameters(
            data, ith_method=ith_method, lasing_threshold_uw=lasing_threshold_uw
        )
        params.update({
            "Row":      row,
            "Column":   col,
            "Site":     site,
            "Filename": csv_path.name,
        })
        records.append(params)

        if generate_liv_curves:
            visualization.plot_liv_curve(
                data, params, row, col, site,
                liv_curve_dir / f"site_{site:03d}_r{row:02d}c{col:02d}.png",
            )

        # Build progress message
        if np.isfinite(params.get("Ith_mA", np.nan)):
            msg = (
                f"Site {site:03d} (r{row:02d},c{col:02d}) – "
                f"{'lasing' if params['Lasing'] else 'no lasing'}, "
                f"Ith={params['Ith_mA']:.1f} mA, "
                f"SE={params['SE_WAA']:.4f} W/A, "
                f"Pmax={params['Pmax_mW']:.3f} mW"
            )
        else:
            msg = (
                f"Site {site:03d} (r{row:02d},c{col:02d}) – "
                f"{'lasing' if params['Lasing'] else 'no lasing'}, "
                f"Pmax={params['Pmax_mW']:.4f} mW"
            )
        if progress_cb:
            progress_cb(i + 1, total, msg)

    if not records:
        raise RuntimeError(
            f"No valid site files could be processed.\n"
            f"  Folder searched : {results_folder}\n"
            f"  CSV files found : {total}\n"
            f"  Skipped (filename): {n_skip_name}\n"
            f"  Skipped (load error): {n_skip_load}"
        )

    # Generate wafer maps and combined overview
    for pname in list(parameter_extractor.models.PARAM_META.keys()):
        grid_data = {
            (r["Row"], r["Column"]): r[pname]
            for r in records
            if np.isfinite(r.get(pname, np.nan))
        }
        if grid_data:
            visualization.plot_wafer_map(
                pname, grid_data, max_row, max_col,
                wafer_map_dir / f"wafer_map_{pname}.png",
            )

    if records:
        visualization.plot_combined_overview(
            records, max_row, max_col,
            output_folder / "wafer_maps_overview.png",
        )

    # Write summary CSV
    output.write_summary_csv(records, output_folder / "summary_parameters.csv")

    # Print statistics
    output.print_statistics(records)

    return records
