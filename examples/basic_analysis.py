#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example 1: Basic VCSEL L-I-V Analysis

This script demonstrates the simplest way to analyze a folder of VCSEL measurement data.

Author: Veronica GaoZhan
Date: February 2026
"""

from pathlib import Path
import vcsel_liv


def main():
    """Run a basic analysis on measurement data."""
    # Define input and output folders
    # Change these paths to match your measurement data location
    results_folder = Path("./data/measurements")
    output_folder = Path("./output/analysis_results")

    if not results_folder.exists():
        print(f"Error: Results folder not found: {results_folder}")
        print("Please update the paths in this script to match your data location.")
        return

    print(f"Analyzing VCSEL measurements from: {results_folder}")
    print(f"Output will be saved to: {output_folder}")

    # Run the full analysis pipeline
    # This will:
    #   1. Load all CSV files from results_folder
    #   2. Extract parameters (Ith, SE, Vth, Pmax, etc.)
    #   3. Generate wafer maps for each parameter
    #   4. Create per-site L-I-V curve plots
    #   5. Write summary CSV file
    #   6. Print statistics to console
    records = vcsel_liv.run_analysis(
        results_folder=results_folder,
        output_folder=output_folder,
        lasing_threshold_uw=10.0,      # 10 µW minimum for "lasing" classification
        generate_liv_curves=True,      # Generate per-site L-I-V plots
        ith_method="adaptive_kink",    # Use adaptive kink method for threshold extraction
    )

    print(f"\nAnalysis complete! Processed {len(records)} sites.")
    print(f"Results saved to: {output_folder}")


if __name__ == "__main__":
    main()
