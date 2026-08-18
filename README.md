# VCSEL L-I-V Analysis

A modular Python package for analyzing VCSEL (Vertical-Cavity Surface-Emitting Laser) L-I-V characteristics, extracting key device parameters, and generating high-quality visualizations.

## Features

- **Parameter Extraction**: Automatically extracts 9 key VCSEL parameters:
  - Threshold current (Ith)
  - Slope efficiency (SE)
  - Threshold voltage (Vth)
  - Peak optical power (Pmax)
  - Rollover current (Iroll)
  - Rollover voltage (Vroll)
  - Series resistance (Rs)
  - Peak wall-plug efficiency (WPE)
  - Lasing classification

- **Multiple Threshold Methods**: Choose between three threshold extraction algorithms:
  - Adaptive kink fitting (default, most robust)
  - Two-segment linear fitting
  - Linear extrapolation

- **Batch Processing**: Analyze multiple wafer folders in a single run

- **Comprehensive Visualization**:
  - Individual wafer maps for each parameter
  - Combined overview figure with all parameters
  - Per-site L-I-V curves with threshold markers
  - Adaptive color-mapping with automatic scaling

- **Data Export**: Save extracted parameters to CSV format for further analysis

- **Statistics**: Automated calculation and display of parameter statistics (mean, std, min, max)

## Installation

### From source

```bash
git clone https://github.com/vvvvvero/VCSEL_LI_V_Analysis.git
cd VCSEL_LI_V_Analysis
pip install -e .
```

### Dependencies

- Python 3.7+
- numpy >= 1.19
- matplotlib >= 3.3

## Quick Start

### Basic Usage

```python
import vcsel_liv
from pathlib import Path

# Run full analysis pipeline
records = vcsel_liv.run_analysis(
    results_folder=Path("./data/measurements"),
    output_folder=Path("./output"),
    lasing_threshold_uw=10.0,
    generate_liv_curves=True,
    ith_method="adaptive_kink",
)
```

### Command-line Interface

```bash
python main.py ./data/measurements ./output --lasing-threshold 10.0 --threshold-method adaptive_kink
```

## Examples

Three example scripts demonstrate different use cases:

### 1. Basic Analysis (`examples/basic_analysis.py`)
Simple example showing how to analyze a single measurement folder and generate all visualizations.

```bash
cd examples
python basic_analysis.py
```

### 2. Batch Analysis (`examples/batch_analysis.py`)
Process multiple wafer measurement folders and combine results into a unified report.

```bash
python batch_analysis.py
```

### 3. Custom Analysis (`examples/custom_analysis.py`)
Advanced example demonstrating:
- Individual file loading
- Comparison of different threshold extraction methods
- Custom per-site visualization
- Direct parameter extraction API

```bash
python custom_analysis.py
```

## Package Structure

```
vcsel_liv_v_analysis/
├── vcsel_liv/                      # Main package
│   ├── __init__.py                 # Public API exports
│   ├── models.py                   # Data models and constants
│   ├── file_io.py                  # CSV loading and filename parsing
│   ├── threshold_extraction.py     # Threshold extraction algorithms
│   ├── parameter_extractor.py      # Main parameter extraction
│   ├── visualization.py            # Plotting functions
│   ├── output.py                   # CSV writing and statistics
│   └── analysis.py                 # Full analysis pipeline
├── examples/                       # Example scripts
│   ├── basic_analysis.py
│   ├── batch_analysis.py
│   └── custom_analysis.py
├── main.py                         # CLI entry point
├── setup.py                        # Package configuration
├── requirements.txt                # Dependencies
└── README.md                       # This file
```

## API Reference

### Main Functions

#### `run_analysis()`
Full analysis pipeline orchestrating all processing steps.

```python
records = vcsel_liv.run_analysis(
    results_folder: Path,
    output_folder: Path,
    lasing_threshold_uw: float = 10.0,
    generate_liv_curves: bool = True,
    ith_method: str = "adaptive_kink",
    progress_cb: Optional[Callable] = None,
) -> list
```

**Parameters**:
- `results_folder`: Directory with per-site CSV files
- `output_folder`: Output directory for results
- `lasing_threshold_uw`: Minimum peak power (µW) for lasing classification
- `generate_liv_curves`: Whether to generate per-site L-I-V plots
- `ith_method`: Threshold extraction method
- `progress_cb`: Optional progress callback function

**Returns**: List of parameter dictionaries, one per site

---

#### `extract_parameters()`
Extract VCSEL parameters from I-V-P data arrays.

```python
params = vcsel_liv.extract_parameters(
    data: dict,
    ith_method: str = "adaptive_kink",
    lasing_threshold_uw: float = 10.0,
) -> dict
```

**Parameters**:
- `data`: Dictionary with keys 'I', 'V', 'P' (numpy arrays)
- `ith_method`: Threshold extraction method
- `lasing_threshold_uw`: Lasing classification threshold

**Returns**: Dictionary with all extracted parameters

---

#### `parse_filename()`
Extract row, column, and site numbers from CSV filename.

```python
row, col, site = vcsel_liv.parse_filename(Path("row_1_col_2_site_001.csv"))
```

---

#### `load_site_csv()`
Load a single CSV measurement file.

```python
data = vcsel_liv.load_site_csv(Path("row_1_col_2_site_001.csv"))
# Returns: {'I': array([...]), 'V': array([...]), 'P': array([...])}
```

---

### Visualization Functions

#### `plot_wafer_map()`
Generate individual color-mapped wafer visualization.

```python
vcsel_liv.plot_wafer_map(
    param_name="Ith_mA",
    grid_data={(1, 1): 5.2, (1, 2): 5.1, ...},
    max_row=10,
    max_col=10,
    output_path=Path("wafer_map_Ith.png"),
)
```

#### `plot_combined_overview()`
Generate single figure with all parameter maps.

```python
vcsel_liv.plot_combined_overview(
    records=records,
    max_row=10,
    max_col=10,
    output_path=Path("overview.png"),
)
```

#### `plot_liv_curve()`
Generate L-I-V curve plot for a single site.

```python
vcsel_liv.plot_liv_curve(
    data={'I': array([...]), 'V': array([...]), 'P': array([...])},
    params={'Ith_mA': 5.2, 'SE_WAA': 0.15, ...},
    row=1,
    col=2,
    site=1,
    output_path=Path("site_001_liv.png"),
)
```

---

### Output Functions

#### `write_summary_csv()`
Export parameters to CSV file.

```python
vcsel_liv.write_summary_csv(
    records=records,
    output_path=Path("summary.csv"),
)
```

#### `print_statistics()`
Print parameter statistics to console.

```python
vcsel_liv.print_statistics(records=records)
```

## Output Files

Analysis generates the following outputs:

```
output_folder/
├── summary_parameters.csv          # Extracted parameters for all sites
├── wafer_maps/
│   ├── wafer_map_Ith_mA.png
│   ├── wafer_map_SE_WAA.png
│   ├── wafer_map_Vth_V.png
│   ├── wafer_map_Pmax_mW.png
│   ├── wafer_map_Iroll_mA.png
│   ├── wafer_map_Vroll_V.png
│   ├── wafer_map_Rs_ohm.png
│   └── wafer_map_WPEmax_pct.png
├── wafer_maps_overview.png         # All maps in single figure
└── liv_curves/                     # Per-site L-I-V plots (optional)
    ├── site_001_r01c01.png
    ├── site_002_r01c02.png
    └── ...
```

## CSV File Format

Input CSV files must have the following columns:
- `Current_A`: Current in Amperes
- `Voltage_V`: Voltage in Volts
- `Optical_Power_W`: Optical power in Watts
- `Status`: Measurement status (only rows with Status="OK" are processed)

Example:

```csv
Current_A,Voltage_V,Optical_Power_W,Status
0.000000,1.450000,0.000000e-12,OK
0.000100,1.460000,1.234e-08,OK
0.000200,1.470000,2.567e-08,OK
...
```

## Threshold Extraction Methods

### Adaptive Kink Method (Default)
Most robust method using local curvature analysis. Smooths the power curve and its derivatives to find the optimal turn-on point, handling various curve shapes (e.g., rollover, compliance limiting).

### Two-Segment Method
Classical piecewise-linear fitting. Scans all potential breakpoints in the 5-70% range of rollover current and finds the split that minimizes total residual error.

### Linear Extrapolation
Simple linear fit to the clearly-lasing region (60-90% of rollover current), extrapolated to zero power.

## Development

### Adding Custom Threshold Methods

The threshold extraction module is modular and extensible:

```python
from vcsel_liv import threshold_extraction

def my_custom_threshold(I, P, Iroll_A):
    """Custom threshold extraction method."""
    # Your implementation here
    return Ith_A, SE_WA  # Return current and slope efficiency

# Use in extract_parameters
params = vcsel_liv.extract_parameters(
    data=data,
    ith_method="custom"  # Will use your method
)
```

## License

MIT License - See LICENSE file for details

## Author

Veronica GaoZhan  
February 2026

## Citation

If you use this package in your research, please cite:

```
GaoZhan, V. (2026). VCSEL L-I-V Analysis: A Python package for extracting 
VCSEL parameters from optical characteristics. 
https://github.com/vvvvvero/VCSEL_LI_V_Analysis
```

## Support

For issues, questions, or contributions, please visit:
https://github.com/vvvvvero/VCSEL_LI_V_Analysis
