#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
VCSEL L-I-V Analysis Package

A modular Python package for analyzing VCSEL (Vertical-Cavity Surface-Emitting Laser)
L-I-V characteristics, extracting key parameters, and generating visualizations.

Author: Veronica GaoZhan
Date: February 2026
"""

__version__ = "1.0.0"
__author__ = "Veronica GaoZhan"

from . import models
from . import file_io
from . import threshold_extraction
from . import parameter_extractor
from . import visualization
from . import output
from . import analysis

# Public API
__all__ = [
    # Core modules
    "models",
    "file_io",
    "threshold_extraction",
    "parameter_extractor",
    "visualization",
    "output",
    "analysis",
    # Key functions
    "parse_filename",
    "load_site_csv",
    "extract_parameters",
    "run_analysis",
    "plot_wafer_map",
    "plot_combined_overview",
    "plot_liv_curve",
    "write_summary_csv",
    "print_statistics",
]

# Convenience exports
from .file_io import parse_filename, load_site_csv
from .parameter_extractor import extract_parameters
from .analysis import run_analysis
from .visualization import plot_wafer_map, plot_combined_overview, plot_liv_curve
from .output import write_summary_csv, print_statistics
