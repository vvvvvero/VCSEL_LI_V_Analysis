#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Command-line interface for VCSEL L-I-V analysis.

Author: Veronica GaoZhan
Date: February 2026
"""

import argparse
from pathlib import Path
import sys

import vcsel_liv


def main(argv=None):
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="VCSEL L-I-V Analysis - Extract and visualize VCSEL parameters",
    )
    parser.add_argument(
        "results_folder",
        type=Path,
        help="Folder containing per-site measurement CSV files",
    )
    parser.add_argument(
        "output_folder",
        type=Path,
        help="Output folder for results (will be created if needed)",
    )
    parser.add_argument(
        "--lasing-threshold",
        type=float,
        default=10.0,
        help="Minimum peak power (µW) for lasing classification (default: 10.0)",
    )
    parser.add_argument(
        "--no-liv-curves",
        action="store_true",
        help="Skip generating per-site L-I-V curve plots",
    )
    parser.add_argument(
        "--threshold-method",
        choices=["adaptive_kink", "two_segment", "linear_extrap"],
        default="adaptive_kink",
        help="Threshold extraction method (default: adaptive_kink)",
    )

    args = parser.parse_args(argv)

    # Validate input folder
    if not args.results_folder.exists():
        print(f"Error: Results folder not found: {args.results_folder}", file=sys.stderr)
        return 1

    print(f"Results folder: {args.results_folder}")
    print(f"Output folder:  {args.output_folder}")
    print(f"Lasing threshold: {args.lasing_threshold} µW")
    print(f"Threshold method: {args.threshold_method}")

    try:
        records = vcsel_liv.run_analysis(
            results_folder=args.results_folder,
            output_folder=args.output_folder,
            lasing_threshold_uw=args.lasing_threshold,
            generate_liv_curves=not args.no_liv_curves,
            ith_method=args.threshold_method,
        )
        print(f"\n✓ Analysis complete! Processed {len(records)} sites.")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
