#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Setup configuration for VCSEL L-I-V Analysis package.

Author: Veronica GaoZhan
Date: February 2026
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="vcsel-liv-analysis",
    version="1.0.0",
    description="VCSEL L-I-V Analysis - Extract and visualize VCSEL parameters",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Veronica GaoZhan",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.7",
    install_requires=[
        "numpy>=1.19",
        "matplotlib>=3.3",
    ],
    entry_points={
        "console_scripts": [
            "vcsel-liv-analysis=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Physics",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    keywords="vcsel optics laser parameters extraction",
)
