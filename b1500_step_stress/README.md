# B1500 Step Stress Measurement

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Synchronized Keysight B1500 + Thorlabs power-meter step stress testing with live monitoring and automated data export.**

© Veronica Gao Zhan – August 2026

---

## Overview

This package provides a modular, extensible framework for performing step stress measurements on photonic devices (VCSELs, lasers, etc.) using the **Keysight B1500 Semiconductor Parameter Analyzer** and **Thorlabs PM100D/PM400 optical power meters**:

- **IV Sweeps** – Point-by-point sourcing via B1500 SMU (IV or VI mode)
- **Optical Power Readout** – Real-time Thorlabs power meter per measurement point
- **Step Stress** – Apply incrementally higher stress levels, measure I-V + optical power after each step
- **Live Monitoring** – Track stress-induced degradation in real time
- **Compliance Detection** – Optional early exit when device hits compliance limit
- **Multi-Point Export** – CSV files per step (IV data, stress data, summary statistics)

---

## Features

| Feature | Detail |
|---------|--------|
| **IV Sweep** | Point-by-point sourcing via Keysight B1500 (IV or VI mode) |
| **Optical Power** | Real-time Thorlabs PM100D / PM400 readout per measurement point |
| **Step Stress** | Incrementally increasing stress levels with duration & monitoring |
| **Compliance Detection** | Optional: move to next step when compliance is reached |
| **Integration Time Control** | Auto ADC, PLC-based, or manual aperture modes |
| **Measurement Range** | Auto-range or user-specified (current or voltage) |
| **Live GUI** | PyQt5 with 4×subplots: I-V, L-I, stress monitoring, degradation curves |
| **CLI Interface** | Full headless operation for scripting & batch testing |
| **CSV Export** | Timestamped per-step files with full data + summary |
| **Callbacks** | Python API for integration with external data pipelines |

---

## Installation

### From Source

```bash
git clone https://github.com/vvvvvero/VCSEL_LI_V_Analysis.git
cd VCSEL_LI_V_Analysis/b1500_step_stress
pip install -e .
```

### Via pip (when available)

```bash
pip install b1500_step_stress
```

### Dependencies

- **NumPy** (data processing)
- **PyVISA** + **PyVISA-py** (hardware communication)
- **PyQt5** (GUI)
- **Matplotlib** (plotting)

---

## Quick Start

### GUI Mode

```bash
python -m b1500_step_stress
```

This launches an interactive window to:
1. Select B1500 and power meter devices
2. Configure IV sweep (start, stop, steps, dwell, compliance)
3. Configure stress parameters (mode, levels, duration, sample rate)
4. Monitor live plots and progress
5. Review summary table after each step

### CLI Mode

```bash
# List available VISA resources
python -m b1500_step_stress --list-resources

# Run test with default parameters
python -m b1500_step_stress \
  --b1500 "GPIB0::17::INSTR" \
  --pm "USB0::0x1313::0x8078::P1234567::INSTR"

# Custom stress parameters
python -m b1500_step_stress \
  --b1500 "GPIB0::17::INSTR" \
  --pm "USB0::0x1313::0x8078::P1234567::INSTR" \
  --stress-start 2.0 --stress-stop 6.0 --stress-step 0.5 \
  --stress-duration 120 \
  --device-name "VCSEL_L12" \
  --output-folder /data/vcsel_test
```

### Python API

```python
from b1500_step_stress import (
    StepStressConfig,
    MeasurementSettings,
    StressSettings,
    B1500Controller,
    ThorlabsPowerMeterController,
    StepStressMeasurementEngine,
)

# Connect to devices
b1500 = B1500Controller()
b1500.connect("GPIB0::17::INSTR")

pm = ThorlabsPowerMeterController()
pm.connect("USB0::0x1313::0x8078::P1234567::INSTR")

# Configure measurement
cfg = StepStressConfig(
    measurement=MeasurementSettings(
        smu=1,
        mode="iv",
        start=0.0,
        stop=3.0,
        steps=31,
        dwell_s=0.1,
        compliance=0.1,
    ),
    stress=StressSettings(
        mode="voltage",
        start_value=2.0,
        stop_value=6.0,
        step_value=0.5,
        duration_s=120,
        sample_interval_s=1.0,
        compliance=0.1,
    ),
)

# Run test
engine = StepStressMeasurementEngine(b1500, pm, cfg)
engine.on_log = print  # Connect callbacks
engine.on_progress = lambda c, t: print(f"Step {c}/{t}")

meas_data, stress_data = engine.run()

# Process results
for point in meas_data:
    print(f"Step {point.step}: V={point.voltage:.3f} V, I={point.current:.3e} A, P={point.optical_power:.3e} W")

# Cleanup
b1500.disconnect()
pm.disconnect()
```

---

## Package Structure

```
b1500_step_stress/
├── __init__.py                    ← Public API
├── __main__.py                    ← CLI entry point (python -m b1500_step_stress)
├── config.py                      ← Data classes (StepStressConfig, MeasurementPoint, etc.)
├── b1500_controller.py            ← B1500 VISA driver (thread-safe)
├── powermeter_controller.py       ← Thorlabs power meter VISA driver (thread-safe)
├── engine.py                      ← StepStressMeasurementEngine (core logic, no GUI)
├── requirements.txt
├── pyproject.toml
└── README.md
```

### Design Principles

1. **Modular** – Each layer (VISA, hardware, engine, UI) is independent  
2. **No GUI dependency** – Engine, controllers, and config work headless  
3. **Thread-safe** – All device communication uses locks  
4. **Callback-based** – Engine emits events; GUI/CLI connect listeners  
5. **Pure data classes** – Config objects have no external dependencies  

---

## Configuration

### Integration Time Modes

The B1500 supports three integration time modes:

```python
# Auto ADC: N samples with high-speed or high-resolution ADC
integration_time = "AUTO_SHORT_1"    # High-speed, 1 sample
integration_time = "AUTO_LONG_1"     # High-resolution, 1 sample
integration_time = "AUTO_SHORT_10"   # High-speed, 10 averaging samples

# Power Line Cycle (PLC): N cycles at 50/60 Hz
integration_time = "PLC_1"           # 1 power line cycle
integration_time = "PLC_5"           # 5 power line cycles

# Manual aperture time (seconds)
integration_time = "MANUAL_0.001"    # 1 ms aperture
```

### Measurement Ranges

Auto-range (recommended for sweeps) or fixed ranges:

```python
from b1500_step_stress import MeasurementSettings

# Current ranges (IV mode)
cfg.measurement.meas_range = None      # Auto-range
cfg.measurement.meas_range = 1e-6      # 1 µA range
cfg.measurement.meas_range = 1e-3      # 1 mA range
cfg.measurement.meas_range = 1.0       # 1 A range

# Voltage ranges (VI mode)
cfg.measurement.meas_range = None      # Auto-range
cfg.measurement.meas_range = 2.0       # 2 V range
cfg.measurement.meas_range = 40.0      # 40 V range
```

### Stress Modes

```python
from b1500_step_stress import StressSettings

# Constant Voltage (monitor current degradation)
stress = StressSettings(
    mode="voltage",
    start_value=2.0,
    stop_value=5.0,
    step_value=0.5,
    duration_s=60,
    compliance=0.1,  # Current compliance
)

# Constant Current (monitor voltage degradation)
stress = StressSettings(
    mode="current",
    start_value=50e-3,
    stop_value=200e-3,
    step_value=10e-3,
    duration_s=60,
    compliance=40,  # Voltage compliance
)

# Early stop on compliance
stress.stop_on_compliance = True  # Move to next step when limit reached
```

---

## Output Files

For each test session, a folder is created: `{device_name}_step_stress_{YYYYMMDD_HHMMSS}/`

```
Device_001_step_stress_20260810_143022/
├── measurement_step_000_stress_0.0000.csv    (baseline IV sweep)
├── measurement_step_001_stress_2.0000.csv    (IV sweep after 1st stress)
├── measurement_step_002_stress_2.5000.csv    (IV sweep after 2nd stress)
├── stress_step_001_level_2.0000.csv          (stress monitoring data)
├── stress_step_002_level_2.5000.csv
├── ...
└── step_summary.csv                          (summary: peak I, peak P, Vth, Rs, etc.)
```

### CSV Format

**Measurement file** (`measurement_step_*.csv`):
```
Step,Stress_Level,Point,Timestamp,Setpoint,Voltage_V,Current_A,Optical_Power_W,Status
0,0.0000,0,2026-08-10T14:30:22,0.0000,0.0000,0.0000,0.0000,OK
0,0.0000,1,2026-08-10T14:30:23,0.1000,0.0991,0.0001,1.2e-06,OK
...
```

**Stress file** (`stress_step_*.csv`):
```
Step,Stress_Level,Timestamp,Elapsed_s,Voltage_V,Current_A,Optical_Power_W,Status
1,2.0000,2026-08-10T14:30:50,0.0,2.0000,0.0500,1.5e-05,OK
1,2.0000,2026-08-10T14:30:51,1.0,2.0000,0.0501,1.5e-05,OK
...
```

**Summary file** (`step_summary.csv`):
```
Step,Stress_Level,Timestamp,Peak_Current_A,Peak_Power_W,Threshold_V,Series_R_Ohm,Stress_Avg_Current_A,Stress_Avg_Power_W
0,0.0000,2026-08-10T14:30:40,0.0500,1.8e-05,1.5,500,0.0,0.0
1,2.0000,2026-08-10T14:31:50,0.0495,1.7e-05,1.55,510,0.0499,1.6e-05
...
```

---

## Troubleshooting

### No VISA Resources Found

```bash
# Reinstall PyVISA backends
pip install --upgrade pyvisa-py
```

### B1500 Connection Timeout

- Check GPIB cable and terminator  
- Verify GPIB address: `gpib_find` utility (comes with Keysight drivers)
- Test with NI Measurement & Automation Explorer or Rohde & Schwarz VISA

### Power Meter Not Detected

- Check USB cable and power (green LED on PM100D)
- Run: `python -m b1500_step_stress --list-resources`
- Test with Thorlabs PM100D software

### GUI Scaling Issues (High DPI)

Set environment variable before running:
```bash
export QT_SCALE_FACTOR=1.5
python -m b1500_step_stress
```

---

## API Reference

### `StepStressConfig`

```python
@dataclass
class StepStressConfig:
    measurement: MeasurementSettings
    stress: StressSettings
    initial_measurement: bool = True
    enable_power_meter: bool = True
    power_wavelength_nm: float = 850.0
    output_folder: str = "results"
    device_name: str = "Device_001"
    autosave: bool = True
```

### `StepStressMeasurementEngine`

```python
class StepStressMeasurementEngine:
    def run() -> Tuple[List[MeasurementPoint], List[StressPoint]]
    def stop() -> None
    
    # Callbacks
    on_log: Callable[[str], None]
    on_progress: Callable[[int, int], None]
    on_phase_change: Callable[[TestPhase], None]
    on_measurement_point: Callable[[MeasurementPoint], None]
    on_stress_point: Callable[[StressPoint], None]
    on_step_complete: Callable[[int, float], None]
```

### `B1500Controller`

```python
class B1500Controller:
    def connect(resource: str, timeout_ms: int = 15000) -> Tuple[bool, str]
    def disconnect() -> None
    def configure_for_measurement(settings: MeasurementSettings) -> None
    def set_bias_and_measure(smu: int, set_value: float, mode: str, 
                             compliance: float, dwell_s: float) -> Tuple[float, float]
    def output_off(smu: int) -> None
    def list_all_resources() -> List[str]
```

### `ThorlabsPowerMeterController`

```python
class ThorlabsPowerMeterController:
    def connect(resource: str, timeout_ms: int = 5000) -> Tuple[bool, str]
    def disconnect() -> None
    def configure(wavelength_nm: float, auto_range: bool = True, 
                  averages: int = 1) -> bool
    def measure_power() -> Tuple[float, str]
    def list_resources(filter_pattern: str = "") -> List[str]
```

---

## Citation

If you use this software in your research, please cite:

```bibtex
@software{b1500_step_stress_2026,
  author = {Gao Zhan, Veronica},
  title = {B1500 Step Stress Measurement},
  year = {2026},
  url = {https://github.com/vvvvvero/VCSEL_LI_V_Analysis},
  note = {Step stress and reliability testing framework}
}
```

---

## License

MIT License – see [LICENSE](LICENSE) for details.

© Veronica Gao Zhan – August 2026

---

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

## Support

For bugs, questions, or feature requests:  
📧 veronicagaozhan@gmail.com  
🐛 [GitHub Issues](https://github.com/vvvvvero/VCSEL_LI_V_Analysis/issues)
