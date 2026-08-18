#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Visualization and plotting functions for VCSEL L-I-V analysis.

Author: Veronica GaoZhan
Date: February 2026
"""

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from . import models


def _fmt(v: float) -> str:
    """Compact numeric label for wafer-map cell annotations."""
    if not np.isfinite(v):
        return ""
    a = abs(v)
    if a >= 100:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    if a >= 1:
        return f"{v:.2f}"
    return f"{v:.3f}"


def _text_color(cmap, norm_val: float) -> str:
    """Return 'white' or 'black' for readable text over a colormapped cell."""
    rgba = cmap(float(np.clip(norm_val, 0.0, 1.0)))
    lum  = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
    return "white" if lum < 0.45 else "black"


def plot_wafer_map(
    param_name: str,
    grid_data: dict,
    max_row: int,
    max_col: int,
    output_path: Path,
    title_prefix: str = "",
    annotate: bool = True,
) -> None:
    """
    Draw a colour-mapped wafer grid and save as PNG.

    Parameters
    ----------
    param_name : str
        Key in PARAM_META
    grid_data : dict
        {(row_1based, col_1based): value}
    max_row : int
        Grid row dimension
    max_col : int
        Grid column dimension
    output_path : Path
        Output PNG file path
    title_prefix : str, optional
        Prepended to figure title (e.g. wafer name)
    annotate : bool, optional
        Whether to write numeric values inside each cell
    """
    meta = models.PARAM_META[param_name]
    grid = np.full((max_row, max_col), np.nan)
    for (r, c), v in grid_data.items():
        if 1 <= r <= max_row and 1 <= c <= max_col:
            grid[r - 1, c - 1] = float(v)

    valid = grid[np.isfinite(grid)]
    if len(valid) == 0:
        return

    vmin = float(meta.get("vmin", np.nanmin(grid)))
    vmax = float(meta.get("vmax", np.nanmax(grid)))
    if np.isclose(vmin, vmax):
        vmax = vmin + 1e-9

    cmap = plt.get_cmap(meta["cmap"]).copy()
    cmap.set_bad(color="#cccccc")

    fig_w = max(5.0, max_col * 1.5 + 2.5)
    fig_h = max(6.0, max_row * 0.65 + 2.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(
        grid,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
        origin="upper",
        interpolation="nearest",
    )

    if annotate:
        for r in range(max_row):
            for c in range(max_col):
                v = grid[r, c]
                if np.isfinite(v):
                    norm_val = (v - vmin) / (vmax - vmin)
                    tc = _text_color(cmap, norm_val)
                    ax.text(
                        c, r, _fmt(v),
                        ha="center", va="center",
                        fontsize=7, color=tc, fontweight="bold",
                    )

    cb = fig.colorbar(im, ax=ax, fraction=0.030, pad=0.03)
    cb.set_label(meta["label"], fontsize=9)

    ax.set_xlabel("Column", fontsize=9)
    ax.set_ylabel("Row", fontsize=9)
    ax.set_xticks(range(max_col))
    ax.set_xticklabels([str(c + 1) for c in range(max_col)], fontsize=8)
    ax.set_yticks(range(max_row))
    ax.set_yticklabels([str(r + 1) for r in range(max_row)], fontsize=8)

    prefix = f"{title_prefix} – " if title_prefix else ""
    ax.set_title(f"{prefix}Wafer Map: {meta['label']}", fontsize=10, fontweight="bold")

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_combined_overview(
    records: list,
    max_row: int,
    max_col: int,
    output_path: Path,
    title_prefix: str = "",
) -> None:
    """
    Single figure with all wafer-map panels side by side.
    
    Parameters
    ----------
    records : list
        List of result dictionaries
    max_row : int
        Grid row dimension
    max_col : int
        Grid column dimension
    output_path : Path
        Output PNG file path
    title_prefix : str, optional
        Prepended to figure title
    """
    param_names = list(models.PARAM_META.keys())
    ncols_fig = 4
    nrows_fig = (len(param_names) + ncols_fig - 1) // ncols_fig

    fig, axes = plt.subplots(
        nrows_fig, ncols_fig,
        figsize=(5.5 * ncols_fig, 4.8 * nrows_fig),
    )
    axes_flat = np.array(axes).flatten()

    for idx, pname in enumerate(param_names):
        ax = axes_flat[idx]
        meta = models.PARAM_META[pname]

        grid = np.full((max_row, max_col), np.nan)
        for rec in records:
            v = rec.get(pname, np.nan)
            r, c = rec["Row"], rec["Column"]
            if np.isfinite(v) and 1 <= r <= max_row and 1 <= c <= max_col:
                grid[r - 1, c - 1] = float(v)

        valid = grid[np.isfinite(grid)]
        if len(valid) == 0:
            ax.axis("off")
            continue

        vmin = float(meta.get("vmin", np.nanmin(grid)))
        vmax = float(meta.get("vmax", np.nanmax(grid)))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1e-9

        cmap = plt.get_cmap(meta["cmap"]).copy()
        cmap.set_bad("#c8c8c8")

        im = ax.imshow(
            grid, cmap=cmap, vmin=vmin, vmax=vmax,
            aspect="equal", origin="upper", interpolation="nearest",
        )
        cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
        cb.set_label(meta["label"], fontsize=6)
        cb.ax.tick_params(labelsize=5)

        for r in range(max_row):
            for c in range(max_col):
                v = grid[r, c]
                if np.isfinite(v):
                    norm_val = (v - vmin) / (vmax - vmin)
                    tc = _text_color(cmap, norm_val)
                    ax.text(c, r, _fmt(v), ha="center", va="center",
                            fontsize=5, color=tc, fontweight="bold")

        ax.set_title(meta["label"], fontsize=7, fontweight="bold")
        ax.set_xticks(range(max_col))
        ax.set_xticklabels([str(c + 1) for c in range(max_col)], fontsize=5)
        ax.set_yticks(range(max_row))
        ax.set_yticklabels([str(r + 1) for r in range(max_row)], fontsize=5)

    for idx in range(len(param_names), len(axes_flat)):
        axes_flat[idx].axis("off")

    prefix = f"{title_prefix} – " if title_prefix else ""
    fig.suptitle(
        f"{prefix}VCSEL Wafer Map Overview",
        fontsize=12, fontweight="bold",
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_liv_curve(
    data: dict,
    params: dict,
    row: int,
    col: int,
    site: int,
    output_path: Path,
) -> None:
    """
    Save a two-panel (L-I, V-I) figure for one site.
    
    Parameters
    ----------
    data : dict
        Dictionary with keys 'I', 'V', 'P' (numpy arrays in A, V, W)
    params : dict
        Extracted parameters dictionary
    row : int
        Wafer row index
    col : int
        Wafer column index
    site : int
        Site number
    output_path : Path
        Output PNG file path
    """
    I_mA = data["I"] * 1e3
    V    = data["V"]
    P_mW = data["P"] * 1e3

    fig, (ax_li, ax_vi) = plt.subplots(1, 2, figsize=(10, 4))

    # L-I
    ax_li.plot(I_mA, P_mW, "b-o", ms=3, lw=1.5, label="L-I")
    if np.isfinite(params.get("Ith_mA", np.nan)):
        ax_li.axvline(
            params["Ith_mA"], color="red", ls="--", lw=1.2,
            label=f"Ith = {params['Ith_mA']:.1f} mA",
        )
    if np.isfinite(params.get("Iroll_mA", np.nan)):
        ax_li.axvline(
            params["Iroll_mA"], color="green", ls=":", lw=1.2,
            label=f"Iroll = {params['Iroll_mA']:.1f} mA",
        )
    ax_li.set_xlabel("Current (mA)", fontsize=9)
    ax_li.set_ylabel("Optical power (mW)", fontsize=9)
    ax_li.set_title(f"L-I  row {row}, col {col}  (site {site:03d})", fontsize=9)
    ax_li.legend(fontsize=7)
    ax_li.grid(True, alpha=0.3)

    # V-I
    ax_vi.plot(I_mA, V, "r-o", ms=3, lw=1.5, label="V-I")
    if (np.isfinite(params.get("Vth_V",  np.nan))
            and np.isfinite(params.get("Ith_mA", np.nan))):
        ax_vi.plot(
            params["Ith_mA"], params["Vth_V"], "ko", ms=6,
            label=f"Vth = {params['Vth_V']:.2f} V",
        )
    ax_vi.set_xlabel("Current (mA)", fontsize=9)
    ax_vi.set_ylabel("Voltage (V)", fontsize=9)
    ax_vi.set_title(f"V-I  row {row}, col {col}  (site {site:03d})", fontsize=9)
    ax_vi.legend(fontsize=7)
    ax_vi.grid(True, alpha=0.3)

    pmax_s = (f"{params['Pmax_mW']:.3f} mW"
              if np.isfinite(params.get("Pmax_mW", np.nan)) else "–")
    wpe_s  = (f"{params['WPEmax_pct']:.2f} %"
              if np.isfinite(params.get("WPEmax_pct", np.nan)) else "–")
    fig.suptitle(
        f"Site {site:03d} | Pmax = {pmax_s} | WPE = {wpe_s}",
        fontsize=9, fontweight="bold",
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
