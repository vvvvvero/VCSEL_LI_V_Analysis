#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example 2: Batch Analysis of Multiple Wafers

This script demonstrates how to analyze multiple wafer measurement folders
in a single batch operation, combining all results into a unified report.

Author: Veronica GaoZhan
Date: February 2026
"""

from pathlib import Path
import vcsel_liv


def main():
    """Run batch analysis on multiple wafer folders."""
    # Parent directory containing multiple wafer results folders
    batch_root = Path("./data/batch")

    # Output directory for combined results
    output_root = Path("./output/batch_results")

    if not batch_root.exists():
        print(f"Error: Batch root folder not found: {batch_root}")
        print("Please update the path in this script to match your data location.")
        return

    # Find all measurement folders
    measurement_folders = sorted([d for d in batch_root.iterdir() if d.is_dir()])
    if not measurement_folders:
        print(f"No measurement folders found in: {batch_root}")
        return

    print(f"Found {len(measurement_folders)} measurement folders")
    print("=" * 70)

    all_records = []

    # Process each wafer folder
    for idx, results_folder in enumerate(measurement_folders, 1):
        wafer_name = results_folder.name
        output_folder = output_root / wafer_name

        print(f"\n[{idx}/{len(measurement_folders)}] Processing: {wafer_name}")

        try:
            records = vcsel_liv.run_analysis(
                results_folder=results_folder,
                output_folder=output_folder,
                lasing_threshold_uw=10.0,
                generate_liv_curves=False,  # Disable L-I-V plots for batch speed
                ith_method="adaptive_kink",
            )
            all_records.extend(records)
            print(f"  ✓ Processed {len(records)} sites")

        except Exception as e:
            print(f"  ✗ Error processing {wafer_name}: {e}")
            continue

    # Write combined summary
    if all_records:
        combined_csv = output_root / "combined_summary.csv"
        vcsel_liv.write_summary_csv(all_records, combined_csv)
        print(f"\n✓ Combined summary saved to: {combined_csv}")

        print("\nOverall Statistics:")
        vcsel_liv.print_statistics(all_records)

    print(f"\nBatch analysis complete! Total sites: {len(all_records)}")


if __name__ == "__main__":
    main()
