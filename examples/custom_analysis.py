#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example 3: Custom Analysis with Parameter Extraction Comparison

This script demonstrates how to:
  1. Load individual measurement files
  2. Extract parameters using different threshold methods
  3. Compare results from different extraction approaches
  4. Custom data processing and filtering

Author: Veronica GaoZhan
Date: February 2026
"""

from pathlib import Path
import numpy as np
import vcsel_liv


def main():
    """Demonstrate custom parameter extraction and comparison."""
    # Path to a single measurement CSV file
    csv_file = Path("./data/measurements/row_1_col_1_site_001.csv")

    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        print("Please update the path in this script.")
        return

    print(f"Loading measurement data from: {csv_file}")

    # Load the measurement data
    data = vcsel_liv.load_site_csv(csv_file)
    if data is None:
        print("Error: Could not load CSV file")
        return

    I = data["I"]
    V = data["V"]
    P = data["P"]

    print(f"Loaded {len(I)} data points")
    print(f"  Current range: {np.min(I)*1e3:.2f} – {np.max(I)*1e3:.2f} mA")
    print(f"  Voltage range: {np.min(V):.2f} – {np.max(V):.2f} V")
    print(f"  Power range: {np.min(P)*1e3:.3f} – {np.max(P)*1e3:.3f} mW")

    print("\n" + "=" * 70)
    print("THRESHOLD EXTRACTION METHOD COMPARISON")
    print("=" * 70)

    # Compare different threshold extraction methods
    methods = ["adaptive_kink", "two_segment", "linear_extrap"]

    results = {}
    for method in methods:
        print(f"\nMethod: {method}")
        params = vcsel_liv.extract_parameters(data, ith_method=method)

        # Display key results
        ith = params.get("Ith_mA", np.nan)
        se = params.get("SE_WAA", np.nan)
        pmax = params.get("Pmax_mW", np.nan)
        lasing = params.get("Lasing", 0)

        print(f"  Ith:     {ith:>8.2f} mA" if np.isfinite(ith) else "  Ith:     (not extracted)")
        print(f"  SE:      {se:>8.4f} W/A" if np.isfinite(se) else "  SE:      (not extracted)")
        print(f"  Pmax:    {pmax:>8.3f} mW" if np.isfinite(pmax) else "  Pmax:    (not calculated)")
        print(f"  Lasing:  {lasing}")

        results[method] = params

    print("\n" + "=" * 70)
    print("PARAMETER DETAILS (ADAPTIVE_KINK METHOD)")
    print("=" * 70)

    params = results["adaptive_kink"]
    field_width = 16

    print(f"{'Threshold current':<{field_width}}: {params.get('Ith_mA', np.nan):>10.3f} mA")
    print(f"{'Slope efficiency':<{field_width}}: {params.get('SE_WAA', np.nan):>10.5f} W/A")
    print(f"{'Threshold voltage':<{field_width}}: {params.get('Vth_V', np.nan):>10.3f} V")
    print(f"{'Peak power':<{field_width}}: {params.get('Pmax_mW', np.nan):>10.4f} mW")
    print(f"{'Rollover current':<{field_width}}: {params.get('Iroll_mA', np.nan):>10.3f} mA")
    print(f"{'Rollover voltage':<{field_width}}: {params.get('Vroll_V', np.nan):>10.3f} V")
    print(f"{'Series resistance':<{field_width}}: {params.get('Rs_ohm', np.nan):>10.3f} Ω")
    print(f"{'Peak WPE':<{field_width}}: {params.get('WPEmax_pct', np.nan):>10.3f} %")
    print(f"{'Lasing':<{field_width}}: {params.get('Lasing', 0)}")

    # Export this single site for inspection
    output_folder = Path("./output/custom_analysis")
    output_folder.mkdir(parents=True, exist_ok=True)

    # Save L-I-V curve
    vcsel_liv.plot_liv_curve(
        data, params,
        row=1, col=1, site=1,
        output_path=output_folder / "example_liv_curve.png",
    )
    print(f"\n✓ L-I-V curve saved to: {output_folder}/example_liv_curve.png")


if __name__ == "__main__":
    main()
