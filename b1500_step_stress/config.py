#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
config.py
=========
Pure data classes for step stress measurement configuration.

Classes defined here have NO external dependencies (only stdlib) so any module
in the project – or any third-party script – can import them in isolation.

Classes
-------
MeasurementSettings      – IV measurement phase configuration
StressSettings           – Stress phase configuration  
StepStressConfig         – Complete test configuration
MeasurementPoint         – One synchronized IV + optical power sample
StressPoint              – One stress monitoring sample
StepSummary              – Summary statistics after a step

© Veronica Gao Zhan – August 2026
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TestPhase(Enum):
    """Enumeration of test phases"""
    IDLE = "idle"
    MEASUREMENT = "measurement"
    STRESS = "stress"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass
class MeasurementSettings:
    """Settings for IV measurement phase (sweep)"""
    
    smu: int = 1
    """SMU channel number (1–10)."""
    
    mode: str = "iv"
    """Sweep direction: ``"iv"`` → source Voltage, measure Current;
    ``"vi"`` → source Current, measure Voltage."""
    
    start: float = 0.0
    """First setpoint value (V or A depending on mode)."""
    
    stop: float = 2.0
    """Last setpoint value."""
    
    steps: int = 21
    """Number of setpoints (including start and stop)."""
    
    dwell_s: float = 0.1
    """Settling time (seconds) between setting source and measuring."""
    
    compliance: float = 0.1
    """Current compliance (A) in IV mode or voltage compliance (V) in VI mode."""
    
    integration_time: str = "AUTO_SHORT_1"
    """Integration-time preset or encoded string.
    
    Examples:
        - "AUTO_SHORT_1", "AUTO_LONG_1" for auto ADC
        - "PLC_2" for power line cycle based
        - "MANUAL_0.001" for manual aperture time
    """
    
    meas_range: Optional[float] = None
    """Measurement range code; ``None`` means auto-range (code 0)."""
    
    @property
    def setpoints(self) -> List[float]:
        """Generate list of setpoints from start, stop, and steps"""
        if self.steps < 2:
            return [self.start]
        return [
            self.start + i * (self.stop - self.start) / (self.steps - 1)
            for i in range(self.steps)
        ]


@dataclass
class StressSettings:
    """Settings for stress phase (constant bias with monitoring)"""
    
    mode: str = "voltage"
    """Stress mode: ``"voltage"`` (constant V) or ``"current"`` (constant I)."""
    
    start_value: float = 2.0
    """Starting stress level (V or A)."""
    
    stop_value: float = 5.0
    """Final stress level."""
    
    step_value: float = 0.5
    """Step increment between levels."""
    
    duration_s: float = 60.0
    """Duration at each stress level (seconds)."""
    
    sample_interval_s: float = 1.0
    """Interval between stress monitoring samples (seconds)."""
    
    compliance: float = 0.1
    """Current compliance (A) in voltage mode, voltage compliance (V) in current mode."""
    
    integration_time: str = "AUTO_SHORT_1"
    """Integration-time preset or encoded string (same format as MeasurementSettings)."""
    
    meas_range: Optional[float] = None
    """Measurement range code; ``None`` means auto-range."""
    
    stop_on_compliance: bool = False
    """If True, move to next stress level when compliance is reached."""
    
    @property
    def stress_levels(self) -> List[float]:
        """Generate list of stress levels from start, stop, and step"""
        levels = []
        current = self.start_value
        if self.step_value > 0:
            while current <= self.stop_value + 1e-9:
                levels.append(current)
                current += self.step_value
        else:
            while current >= self.stop_value - 1e-9:
                levels.append(current)
                current += self.step_value
        return levels
    
    @property
    def num_steps(self) -> int:
        """Total number of stress steps"""
        return len(self.stress_levels)


@dataclass
class StepStressConfig:
    """Complete configuration for step stress test"""
    
    measurement: MeasurementSettings = field(default_factory=MeasurementSettings)
    """Measurement (IV sweep) settings."""
    
    stress: StressSettings = field(default_factory=StressSettings)
    """Stress phase settings."""
    
    initial_measurement: bool = True
    """If True, run initial measurement (step 0) before first stress."""
    
    enable_power_meter: bool = True
    """If False, optical power readout is skipped (optical_power = 0)."""
    
    power_wavelength_nm: float = 850.0
    """Centre wavelength for power-meter responsivity correction (nm)."""
    
    output_folder: str = "results"
    """Folder where session data will be saved."""
    
    device_name: str = "Device_001"
    """Device identifier for output file naming."""
    
    autosave: bool = True
    """If True, measurement and stress data are saved to CSV automatically."""


@dataclass
class MeasurementPoint:
    """One synchronized IV + optical power measurement sample"""
    
    step: int
    """Stress step number (0 = baseline, no stress applied)."""
    
    stress_level: float
    """The stress level applied before this measurement."""
    
    point_index: int
    """Index within the IV sweep (0 to steps-1)."""
    
    timestamp: float
    """Unix timestamp (seconds)."""
    
    setpoint: float
    """The setpoint value sent to the SMU (V or A)."""
    
    voltage: float
    """Measured voltage (V)."""
    
    current: float
    """Measured current (A)."""
    
    optical_power: float
    """Measured optical power (W)."""
    
    status: str = "OK"
    """Status string (e.g., "OK", "No power meter", "Error")."""


@dataclass
class StressPoint:
    """One stress monitoring sample (constant bias with live readout)"""
    
    step: int
    """Stress step number."""
    
    stress_level: float
    """The applied stress level (V or A)."""
    
    timestamp: float
    """Unix timestamp (seconds)."""
    
    elapsed_s: float
    """Elapsed time since start of this stress phase (seconds)."""
    
    voltage: float
    """Measured voltage (V)."""
    
    current: float
    """Measured current (A)."""
    
    optical_power: float
    """Measured optical power (W)."""
    
    status: str = "OK"
    """Status string."""


@dataclass
class StepSummary:
    """Summary statistics after a step measurement"""
    
    step: int
    """Step number."""
    
    stress_level: float
    """Applied stress level (V or A)."""
    
    timestamp: str
    """ISO format timestamp of measurement."""
    
    peak_current: float
    """Maximum current during IV sweep (A)."""
    
    peak_power: float
    """Maximum optical power during IV sweep (W)."""
    
    threshold_voltage: float
    """Estimated threshold voltage (V)."""
    
    series_resistance: float
    """Estimated series resistance from high-current region (Ω)."""
    
    stress_avg_current: float
    """Average current during stress phase (A)."""
    
    stress_avg_power: float
    """Average optical power during stress phase (W)."""
