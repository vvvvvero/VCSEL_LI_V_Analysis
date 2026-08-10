#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B1500 + Thorlabs Power Meter Step Stress Measurement

This script performs step stress testing with increasing stress levels:
  Measurement → Stress(V1) → Measurement → Stress(V2) → Measurement → Stress(V3) → ...

The stress voltage/current increases by a fixed step after each cycle.


Test Flow:
1. Initial IV + Power measurement (baseline)
2. Apply stress at level V1 for configured duration
3. IV + Power measurement
4. Apply stress at level V2 (V1 + step)
5. Repeat until stress reaches stop level
6. Final summary and data export

Author: Veronica GaoZhan 
Date: February 2026
"""

import sys
import os
import csv
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
                             QDoubleSpinBox, QTextEdit, QFileDialog, QMessageBox, QProgressBar,
                             QGridLayout, QCheckBox, QRadioButton, QButtonGroup, QSplitter,
                             QStatusBar, QFrame, QScrollArea, QTabWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush

import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

try:
    import pyvisa
    from pyvisa.errors import VisaIOError
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False
    print("Warning: pyvisa not installed. Install with: pip install pyvisa pyvisa-py")


# Suppress Windows error dialogs
try:
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
except (AttributeError, OSError, TypeError):
    pass


# =============================================================================
# Enums and Data Classes
# =============================================================================

class TestPhase(Enum):
    IDLE = "idle"
    MEASUREMENT = "measurement"
    STRESS = "stress"
    COMPLETED = "completed"
    STOPPED = "stopped"


# No enums needed - using string-based configuration like b1500_powermeter_synchronized.py


@dataclass
class MeasurementSettings:
    """Settings for measurement phase (IV sweep)"""
    smu: int = 1
    mode: str = "iv"  # "iv" or "vi"
    start: float = 0.0
    stop: float = 2.0
    steps: int = 21
    dwell_s: float = 0.1
    compliance: float = 0.1
    
    # Integration time settings (same format as b1500_powermeter_synchronized.py)
    # Format: "AUTO_SHORT_N", "AUTO_LONG_N", "PLC_N", "MANUAL_aperture"
    integration_time: str = "AUTO_SHORT_1"
    
    # Measurement range (0 = auto, or specific range code)
    meas_range: Optional[float] = None
    
    @property
    def setpoints(self) -> List[float]:
        if self.steps < 2:
            return [self.start]
        return [
            self.start + i * (self.stop - self.start) / (self.steps - 1)
            for i in range(self.steps)
        ]


@dataclass
class StressSettings:
    """Settings for stress phase"""
    mode: str = "voltage"  # "voltage" or "current"
    start_value: float = 2.0  # Starting stress level
    stop_value: float = 5.0   # Final stress level
    step_value: float = 0.5   # Step increment
    duration_s: float = 60.0  # Duration at each stress level
    sample_interval_s: float = 1.0  # Monitoring sample interval
    compliance: float = 0.1
    
    # Integration time settings (same format as b1500_powermeter_synchronized.py)
    # Format: "AUTO_SHORT_N", "AUTO_LONG_N", "PLC_N", "MANUAL_aperture"
    integration_time: str = "AUTO_SHORT_1"
    
    # Measurement range (0 = auto, or specific range code)
    meas_range: Optional[float] = None
    
    # Stop on compliance: move to next step when compliance is reached
    stop_on_compliance: bool = False
    
    @property
    def stress_levels(self) -> List[float]:
        """Generate list of stress levels"""
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
        return len(self.stress_levels)


@dataclass
class StepStressConfig:
    """Configuration for the entire step stress test"""
    measurement: MeasurementSettings = field(default_factory=MeasurementSettings)
    stress: StressSettings = field(default_factory=StressSettings)
    
    initial_measurement: bool = True  # Do initial measurement before first stress
    
    # Power meter settings
    enable_power_meter: bool = True
    power_wavelength_nm: float = 850.0
    
    # Output settings
    output_folder: str = "results"
    device_name: str = "Device_001"
    autosave: bool = True


@dataclass
class MeasurementPoint:
    """Single IV measurement point"""
    step: int  # Stress step number (0 = baseline)
    stress_level: float  # The stress level applied before this measurement
    point_index: int
    timestamp: float
    setpoint: float
    voltage: float
    current: float
    optical_power: float
    status: str = "OK"


@dataclass
class StressPoint:
    """Single stress monitoring point"""
    step: int
    stress_level: float
    timestamp: float
    elapsed_s: float
    voltage: float
    current: float
    optical_power: float
    status: str = "OK"


@dataclass
class StepSummary:
    """Summary of a step measurement"""
    step: int
    stress_level: float
    timestamp: str
    peak_current: float
    peak_power: float
    threshold_voltage: float
    series_resistance: float
    stress_avg_current: float  # Average current during stress
    stress_avg_power: float    # Average power during stress


# =============================================================================
# Thorlabs Power Meter Controller
# =============================================================================

class ThorlabsPowerMeterController:
    """Controller for Thorlabs PM100D/PM400 power meters"""
    
    SCPI_IDN = "*IDN?"
    SCPI_MEAS_POWER = "MEAS:POW?"
    SCPI_CONF_POWER = "CONF:POW"
    SCPI_SET_WAVELENGTH = "SENS:CORR:WAV {}"
    SCPI_AUTO_RANGE_ON = "SENS:POW:RANG:AUTO ON"
    SCPI_SET_AVERAGES = "SENS:AVER:COUN {}"
    
    def __init__(self):
        self.rm = None
        self.inst = None
        self.resource: Optional[str] = None
        self.idn: str = ""
        self.lock = threading.Lock()
        self.connected = False
    
    def _resource_manager(self):
        try:
            return pyvisa.ResourceManager()
        except Exception:
            return pyvisa.ResourceManager("@py")
    
    def list_resources(self, filter_pattern: str = "") -> List[str]:
        if not PYVISA_AVAILABLE:
            return []
        rm = self._resource_manager()
        try:
            all_resources = rm.list_resources()
            if filter_pattern:
                filtered = [r for r in all_resources if filter_pattern.upper() in r.upper()]
                return sorted(filtered)
            return sorted(all_resources)
        except Exception:
            return []
        finally:
            try:
                rm.close()
            except:
                pass
    
    def connect(self, resource: str, timeout_ms: int = 5000) -> Tuple[bool, str]:
        self.disconnect()
        try:
            self.rm = self._resource_manager()
            self.inst = self.rm.open_resource(resource)
            self.inst.timeout = timeout_ms
            self.inst.write_termination = "\n"
            self.inst.read_termination = "\n"
            
            with self.lock:
                self.idn = self.inst.query(self.SCPI_IDN).strip()
                self.inst.write(self.SCPI_CONF_POWER)
                time.sleep(0.1)
            
            self.resource = resource
            self.connected = True
            return True, f"Connected: {self.idn}"
        except Exception as exc:
            self.disconnect()
            return False, f"Connection failed: {exc}"
    
    def disconnect(self) -> None:
        if self.inst is not None:
            try:
                self.inst.close()
            except:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except:
                pass
        self.inst = None
        self.rm = None
        self.resource = None
        self.idn = ""
        self.connected = False
    
    def configure(self, wavelength_nm: float, auto_range: bool = True, 
                  averages: int = 1) -> bool:
        if not self.inst:
            return False
        try:
            with self.lock:
                self.inst.write(self.SCPI_SET_WAVELENGTH.format(wavelength_nm))
                time.sleep(0.05)
                if auto_range:
                    self.inst.write(self.SCPI_AUTO_RANGE_ON)
                self.inst.write(self.SCPI_SET_AVERAGES.format(averages))
            return True
        except Exception:
            return False
    
    def measure_power(self) -> Tuple[float, str]:
        if not self.inst:
            return 0.0, "Not connected"
        try:
            with self.lock:
                resp = self.inst.query(self.SCPI_MEAS_POWER).strip()
            power = float(resp)
            return power, "OK"
        except ValueError:
            return 0.0, "Parse error"
        except Exception as e:
            return 0.0, f"Error: {e}"


# =============================================================================
# B1500 Controller
# =============================================================================

class B1500Controller:
    """Controller for Keysight B1500 Semiconductor Parameter Analyzer"""
    
    def __init__(self):
        self.rm = None
        self.inst = None
        self.resource: Optional[str] = None
        self.idn: str = ""
        self.lock = threading.Lock()
        self.connected = False
    
    def _resource_manager(self):
        try:
            return pyvisa.ResourceManager()
        except Exception:
            return pyvisa.ResourceManager("@py")
    
    def list_all_resources(self) -> List[str]:
        if not PYVISA_AVAILABLE:
            return []
        rm = self._resource_manager()
        try:
            return sorted(rm.list_resources())
        except Exception:
            return []
        finally:
            try:
                rm.close()
            except:
                pass
    
    def connect(self, resource: str, timeout_ms: int = 15000) -> Tuple[bool, str]:
        self.disconnect()
        try:
            self.rm = self._resource_manager()
            self.inst = self.rm.open_resource(resource)
            self.inst.timeout = timeout_ms
            self.inst.write_termination = "\n"
            self.inst.read_termination = "\n"
            
            with self.lock:
                self.idn = self.inst.query("*IDN?").strip()
                self.inst.write("FMT 1,0")
                time.sleep(0.1)
            
            self.resource = resource
            self.connected = True
            return True, f"Connected: {self.idn}"
        except Exception as exc:
            self.disconnect()
            return False, f"Connection failed: {exc}"
    
    def disconnect(self) -> None:
        if self.inst is not None:
            try:
                self.inst.close()
            except:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except:
                pass
        self.inst = None
        self.rm = None
        self.resource = None
        self.idn = ""
        self.connected = False
    
    def _safe_read(self) -> str:
        if not self.inst:
            return ""
        try:
            raw = self.inst.read_raw()
            for encoding in ['ascii', 'latin-1', 'utf-8']:
                try:
                    return raw.decode(encoding).strip()
                except UnicodeDecodeError:
                    continue
            return raw.decode('ascii', errors='ignore').strip()
        except Exception:
            return ""
    
    def set_integration_time(self, smu: int, integration: str) -> None:
        """Set integration time for measurement
        
        Args:
            smu: SMU channel number
            integration: Integration time string in format:
                - "AUTO_SHORT_N" or "AUTO_LONG_N" for auto ADC
                - "PLC_N" for power line cycle based
                - "MANUAL_aperture" for manual aperture time
                - "SHORT", "MEDIUM", "LONG" for simple modes
        """
        if not self.inst:
            raise RuntimeError("Not connected")
        
        with self.lock:
            integration_upper = integration.upper()
            
            if integration_upper.startswith("AUTO_"):
                parts = integration.split("_")
                if len(parts) >= 3:
                    mode_type = parts[1].upper()
                    try:
                        num = int(parts[2])
                    except:
                        num = 1
                    if mode_type == "SHORT":
                        self.inst.write(f"AAD {smu},0")  # High-speed ADC
                        self.inst.write(f"AIT 0,0,{num}")  # Type 0, Mode 0, N
                    elif mode_type == "LONG":
                        self.inst.write(f"AAD {smu},0")
                        self.inst.write(f"AIT 1,0,{num}")  # Type 1 (HR ADC), Mode 0, N
                    else:
                        self.inst.write(f"AAD {smu},0")
                        self.inst.write(f"AIT 0,0,{num}")
                else:
                    self.inst.write(f"AAD {smu},0")
                    
            elif integration_upper.startswith("PLC_"):
                try:
                    plc_count = int(integration.split("_")[1])
                except:
                    plc_count = 1
                self.inst.write(f"AIT 0,2,{plc_count}")  # Type 0, Mode 2 (PLC), N
                
            elif integration_upper.startswith("MANUAL_"):
                try:
                    aperture = float(integration.split("_")[1])
                except:
                    aperture = 0.001
                self.inst.write(f"AIT 0,1,{aperture}")  # Type 0, Mode 1 (manual), time
                
            elif integration_upper in ["SHORT", "MEDIUM", "LONG"]:
                self.inst.write(f"AAD {smu},{integration_upper}")
            else:
                # Try to parse as a float (manual aperture)
                try:
                    aperture = float(integration)
                    self.inst.write(f"AIT 0,1,{aperture}")
                except ValueError:
                    self.inst.write(f"AAD {smu},MEDIUM")
            
            time.sleep(0.05)
    
    def configure_for_measurement(self, settings: MeasurementSettings) -> None:
        """Configure B1500 for IV measurement phase"""
        smu = settings.smu
        with self.lock:
            if not self.inst:
                raise RuntimeError("Not connected")
            
            # Clear errors
            try:
                for _ in range(5):
                    err = self.inst.query("ERR?")
                    if err.strip().startswith("0"):
                        break
            except:
                pass
            time.sleep(0.1)
            
            self.inst.write("FMT 1,0")
            time.sleep(0.05)
            self.inst.write(f"CN {smu}")
            time.sleep(0.1)
            self.inst.write("AV 1,0")
            time.sleep(0.05)
            
            # Set measurement range
            range_code = settings.meas_range if settings.meas_range is not None else 0
            if settings.mode == "iv":
                self.inst.write(f"RI {smu},{range_code}")
            else:
                self.inst.write(f"RV {smu},{range_code}")
            time.sleep(0.05)
            
            self.inst.write(f"MM 1,{smu}")  # Spot measurement mode
        
        # Set integration time (outside lock to use the method)
        self.set_integration_time(smu, settings.integration_time)
    
    def configure_for_stress(self, smu: int, settings: StressSettings) -> None:
        """Configure B1500 for stress monitoring phase"""
        with self.lock:
            if not self.inst:
                raise RuntimeError("Not connected")
            
            self.inst.write("FMT 1,0")
            time.sleep(0.05)
            self.inst.write(f"CN {smu}")
            time.sleep(0.1)
            self.inst.write("AV 1,0")
            time.sleep(0.05)
            
            # Set measurement range for stress monitoring
            range_code = settings.meas_range if settings.meas_range is not None else 0
            if settings.mode == "voltage":
                self.inst.write(f"RI {smu},{range_code}")  # Measure current
            else:
                self.inst.write(f"RV {smu},{range_code}")  # Measure voltage
            time.sleep(0.05)
            
            self.inst.write(f"MM 1,{smu}")
        
        # Set integration time for stress monitoring
        self.set_integration_time(smu, settings.integration_time)
    
    def set_bias_and_measure(self, smu: int, set_value: float, mode: str, 
                             compliance: float, dwell_s: float = 0.1) -> Tuple[float, float]:
        """Set source and measure at single point"""
        with self.lock:
            if not self.inst:
                raise RuntimeError("Not connected")
            
            try:
                if mode in ["iv", "voltage"]:
                    self.inst.write(f"DV {smu},0,{set_value},{compliance}")
                else:
                    self.inst.write(f"DI {smu},0,{set_value},{compliance}")
                
                if dwell_s > 0:
                    time.sleep(dwell_s)
                
                self.inst.write("XE")
                
                old_timeout = self.inst.timeout
                self.inst.timeout = 5000
                try:
                    resp = self._safe_read()
                finally:
                    self.inst.timeout = old_timeout
                    
            except Exception as e:
                return (set_value, 0.0) if mode in ["iv", "voltage"] else (0.0, set_value)
        
        # Parse response
        try:
            if not resp:
                return (set_value, 0.0) if mode in ["iv", "voltage"] else (0.0, set_value)
            
            parts = resp.replace(";", ",").split(",")
            values = []
            
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                try:
                    num_start = 0
                    for i, c in enumerate(p):
                        if c in '+-0123456789.':
                            num_start = i
                            break
                    num_str = p[num_start:]
                    if num_str:
                        values.append(float(num_str))
                except:
                    pass
            
            if len(values) >= 1:
                measured = values[0]
                if mode in ["iv", "voltage"]:
                    return set_value, measured  # V_set, I_meas
                else:
                    return measured, set_value  # V_meas, I_set
            
            return (set_value, 0.0) if mode in ["iv", "voltage"] else (0.0, set_value)
                
        except Exception:
            return (set_value, 0.0) if mode in ["iv", "voltage"] else (0.0, set_value)
    
    def output_off(self, smu: int) -> None:
        """Turn off SMU output"""
        if not self.inst:
            return
        with self.lock:
            try:
                self.inst.write(f"DV {smu},0,0,0.01")
                time.sleep(0.05)
                self.inst.write(f"CL {smu}")
            except:
                pass


# =============================================================================
# Step Stress Measurement Engine
# =============================================================================

class StepStressMeasurementEngine:
    """Engine for running step stress measurements"""
    
    def __init__(self, b1500: B1500Controller, power_meter: ThorlabsPowerMeterController,
                 config: StepStressConfig):
        self.b1500 = b1500
        self.power_meter = power_meter
        self.config = config
        
        # Data storage
        self.measurement_data: List[MeasurementPoint] = []
        self.stress_data: List[StressPoint] = []
        self.step_summaries: List[StepSummary] = []
        
        # State
        self.running = False
        self.stop_requested = False
        self.current_phase = TestPhase.IDLE
        self.current_step = 0
        self.current_stress_level = 0.0
        
        # Callbacks
        self.on_measurement_point = None
        self.on_stress_point = None
        self.on_phase_change = None
        self.on_step_complete = None
        self.on_progress = None
        self.on_log = None
        
        # Output
        self.session_folder: Optional[Path] = None
    
    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{timestamp}] {message}"
        print(msg)
        if self.on_log:
            self.on_log(msg)
    
    def set_phase(self, phase: TestPhase):
        self.current_phase = phase
        if self.on_phase_change:
            self.on_phase_change(phase)
    
    def run(self) -> Tuple[List[MeasurementPoint], List[StressPoint]]:
        """Run the complete step stress test"""
        self.running = True
        self.stop_requested = False
        self.measurement_data = []
        self.stress_data = []
        self.step_summaries = []
        
        # Create session folder
        self._create_session_folder()
        
        # Configure power meter
        if self.power_meter.connected and self.config.enable_power_meter:
            self.power_meter.configure(wavelength_nm=self.config.power_wavelength_nm)
            self.log(f"Power meter configured: λ={self.config.power_wavelength_nm}nm")
        
        stress_levels = self.config.stress.stress_levels
        total_steps = len(stress_levels)
        
        self.log(f"Starting step stress test: {total_steps} stress levels")
        self.log(f"Stress range: {self.config.stress.start_value} → {self.config.stress.stop_value} "
                f"(step: {self.config.stress.step_value})")
        self.log(f"Stress mode: {self.config.stress.mode}")
        self.log(f"Stress duration per level: {self.config.stress.duration_s}s")
        self.log("-" * 60)
        self.log(f"Measurement integration: {self.config.measurement.integration_time}")
        self.log(f"Stress integration: {self.config.stress.integration_time}")
        
        try:
            # Initial measurement (step 0, stress_level = 0)
            if self.config.initial_measurement:
                self.current_step = 0
                self.current_stress_level = 0.0
                self._run_measurement_phase()
                if self.stop_requested:
                    return self.measurement_data, self.stress_data
            
            # Step stress loop
            for step_idx, stress_level in enumerate(stress_levels, start=1):
                if self.stop_requested:
                    self.log("Test stopped by user")
                    break
                
                self.current_step = step_idx
                self.current_stress_level = stress_level
                
                self.log(f"\n{'='*60}")
                self.log(f"STEP {step_idx}/{total_steps}: Stress Level = {stress_level:.4f} "
                        f"{'V' if self.config.stress.mode == 'voltage' else 'A'}")
                self.log(f"{'='*60}")
                
                # Stress phase
                self._run_stress_phase(stress_level)
                if self.stop_requested:
                    break
                
                # Measurement phase
                self._run_measurement_phase()
                
                # Progress callback
                if self.on_progress:
                    self.on_progress(step_idx, total_steps)
                
                # Step complete callback
                if self.on_step_complete:
                    self.on_step_complete(step_idx, stress_level)
            
            # Turn off output
            if self.b1500.connected:
                self.b1500.output_off(self.config.measurement.smu)
            
            # Save final summary
            self._save_summary()
            
            self.set_phase(TestPhase.COMPLETED if not self.stop_requested else TestPhase.STOPPED)
            self.log(f"\nTest complete. {len(self.measurement_data)} measurement points, "
                    f"{len(self.stress_data)} stress points recorded.")
            
        except Exception as e:
            self.log(f"Test error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
        
        return self.measurement_data, self.stress_data
    
    def _run_measurement_phase(self):
        """Run IV + power measurement sweep"""
        self.set_phase(TestPhase.MEASUREMENT)
        self.log(f"Starting measurement phase (Step {self.current_step}, "
                f"after stress: {self.current_stress_level})")
        
        cfg = self.config.measurement
        setpoints = cfg.setpoints
        step_data = []
        
        # Configure B1500 for measurement
        if self.b1500.connected:
            try:
                self.b1500.configure_for_measurement(cfg)
                self.log(f"  B1500 configured: integration={cfg.integration_time}, "
                        f"range={cfg.meas_range}")
            except Exception as e:
                self.log(f"  B1500 config error: {e}")
        
        for idx, setpoint in enumerate(setpoints):
            if self.stop_requested:
                break
            
            timestamp = time.time()
            
            # IV measurement
            if self.b1500.connected:
                voltage, current = self.b1500.set_bias_and_measure(
                    cfg.smu, setpoint, cfg.mode, cfg.compliance, cfg.dwell_s
                )
            else:
                voltage = setpoint if cfg.mode == "iv" else 0.0
                current = 0.0 if cfg.mode == "iv" else setpoint
            
            # Optical power
            if self.power_meter.connected and self.config.enable_power_meter:
                power, status = self.power_meter.measure_power()
            else:
                power = 0.0
                status = "No power meter"
            
            point = MeasurementPoint(
                step=self.current_step,
                stress_level=self.current_stress_level,
                point_index=idx,
                timestamp=timestamp,
                setpoint=setpoint,
                voltage=voltage,
                current=current,
                optical_power=power,
                status=status
            )
            
            self.measurement_data.append(point)
            step_data.append(point)
            
            if self.on_measurement_point:
                self.on_measurement_point(point)
        
        # Turn off bias after measurement
        if self.b1500.connected:
            self.b1500.output_off(cfg.smu)
        
        # Save measurement data for this step
        self._save_measurement_step(step_data)
        
        # Calculate step summary
        if step_data:
            summary = self._calculate_summary(step_data, [], self.current_stress_level)
            self.step_summaries.append(summary)
        
        self.log(f"  Measurement complete: {len(step_data)} points")
    
    def _run_stress_phase(self, stress_level: float):
        """Run stress phase with monitoring"""
        self.set_phase(TestPhase.STRESS)
        
        cfg = self.config.stress
        mode_unit = 'V' if cfg.mode == 'voltage' else 'A'
        self.log(f"Starting stress phase: {stress_level:.4f}{mode_unit} for {cfg.duration_s}s")
        
        # Configure B1500 for stress monitoring
        if self.b1500.connected:
            try:
                self.b1500.configure_for_stress(self.config.measurement.smu, cfg)
                self.log(f"  B1500 stress config: integration={cfg.integration_time}, "
                        f"range={cfg.meas_range}")
            except Exception as e:
                self.log(f"  B1500 stress config error: {e}")
        
        start_time = time.time()
        end_time = start_time + cfg.duration_s
        step_stress_data = []
        
        # Apply initial stress
        if self.b1500.connected:
            try:
                smu = self.config.measurement.smu
                with self.b1500.lock:
                    if cfg.mode == "voltage":
                        self.b1500.inst.write(f"DV {smu},0,{stress_level},{cfg.compliance}")
                    else:
                        self.b1500.inst.write(f"DI {smu},0,{stress_level},{cfg.compliance}")
            except Exception as e:
                self.log(f"  Stress setup error: {e}")
                return
        
        sample_count = 0
        while time.time() < end_time and not self.stop_requested:
            timestamp = time.time()
            elapsed = timestamp - start_time
            
            # Monitor current/voltage
            if self.b1500.connected:
                voltage, current = self.b1500.set_bias_and_measure(
                    self.config.measurement.smu, stress_level, cfg.mode,
                    cfg.compliance, dwell_s=0.01
                )
            else:
                voltage = stress_level if cfg.mode == "voltage" else 0.0
                current = 0.0 if cfg.mode == "voltage" else stress_level
            
            # Monitor optical power
            if self.power_meter.connected and self.config.enable_power_meter:
                power, status = self.power_meter.measure_power()
            else:
                power = 0.0
                status = "No power meter"
            
            point = StressPoint(
                step=self.current_step,
                stress_level=stress_level,
                timestamp=timestamp,
                elapsed_s=elapsed,
                voltage=voltage,
                current=current,
                optical_power=power,
                status=status
            )
            
            self.stress_data.append(point)
            step_stress_data.append(point)
            sample_count += 1
            
            if self.on_stress_point:
                self.on_stress_point(point)
            
            # Log every 10 seconds
            if sample_count % max(1, int(10 / cfg.sample_interval_s)) == 0:
                self.log(f"  Stress @{elapsed:.1f}s: I={current:.4e}A, P={power:.4e}W")
            
            # Check for compliance condition
            if cfg.stop_on_compliance:
                compliance_reached = False
                if cfg.mode == "voltage":
                    # In constant voltage mode, check if current hit compliance
                    if abs(current) >= abs(cfg.compliance) * 0.99:  # 99% of compliance
                        compliance_reached = True
                else:
                    # In constant current mode, check if voltage hit compliance
                    if abs(voltage) >= abs(cfg.compliance) * 0.99:  # 99% of compliance
                        compliance_reached = True
                
                if compliance_reached:
                    self.log(f"  ⚠ Compliance reached at {elapsed:.1f}s - moving to next step")
                    break
            
            # Wait for next sample
            next_sample_time = start_time + sample_count * cfg.sample_interval_s
            sleep_time = next_sample_time - time.time()
            if sleep_time > 0:
                time.sleep(min(sleep_time, 0.5))
        
        # Save stress data for this step
        self._save_stress_step(step_stress_data, stress_level)
        
        # Update summary with stress data
        if self.step_summaries and step_stress_data:
            summary = self.step_summaries[-1]
            currents = [p.current for p in step_stress_data]
            powers = [p.optical_power for p in step_stress_data]
            # Will update after measurement phase creates the summary
        
        self.log(f"  Stress complete: {len(step_stress_data)} samples, "
                f"duration: {time.time() - start_time:.1f}s")
    
    def _calculate_summary(self, meas_data: List[MeasurementPoint], 
                           stress_data: List[StressPoint],
                           stress_level: float) -> StepSummary:
        """Calculate summary parameters from measurement data"""
        voltages = [p.voltage for p in meas_data]
        currents = [p.current for p in meas_data]
        powers = [p.optical_power for p in meas_data]
        
        peak_current = max(currents) if currents else 0.0
        peak_power = max(powers) if powers else 0.0
        
        # Estimate threshold voltage
        threshold_v = 0.0
        for v, i in zip(voltages, currents):
            if abs(i) > 1e-6:
                threshold_v = v
                break
        
        # Estimate series resistance
        series_r = 0.0
        if len(voltages) > 5:
            try:
                n_fit = max(3, len(voltages) // 3)
                v_fit = np.array(voltages[-n_fit:])
                i_fit = np.array(currents[-n_fit:])
                if np.std(i_fit) > 0:
                    slope, _ = np.polyfit(i_fit, v_fit, 1)
                    series_r = abs(slope)
            except:
                pass
        
        # Stress averages
        stress_avg_current = 0.0
        stress_avg_power = 0.0
        if stress_data:
            stress_avg_current = np.mean([p.current for p in stress_data])
            stress_avg_power = np.mean([p.optical_power for p in stress_data])
        
        return StepSummary(
            step=self.current_step,
            stress_level=stress_level,
            timestamp=datetime.now().isoformat(),
            peak_current=peak_current,
            peak_power=peak_power,
            threshold_voltage=threshold_v,
            series_resistance=series_r,
            stress_avg_current=stress_avg_current,
            stress_avg_power=stress_avg_power
        )
    
    def _create_session_folder(self):
        """Create session folder for output files"""
        base_path = Path(self.config.output_folder)
        if not base_path.is_absolute():
            base_path = Path(__file__).parent / self.config.output_folder
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_folder = base_path / f"{self.config.device_name}_step_stress_{timestamp}"
        self.session_folder.mkdir(parents=True, exist_ok=True)
        self.log(f"Session folder: {self.session_folder}")
    
    def _save_measurement_step(self, data: List[MeasurementPoint]):
        """Save measurement data for a step"""
        if not data or not self.config.autosave or not self.session_folder:
            return
        
        filename = f"measurement_step_{self.current_step:03d}_stress_{self.current_stress_level:.4f}.csv"
        filepath = self.session_folder / filename
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Step", "Stress_Level", "Point", "Timestamp", "Setpoint",
                "Voltage_V", "Current_A", "Optical_Power_W", "Status"
            ])
            for p in data:
                writer.writerow([
                    p.step, f"{p.stress_level:.6e}", p.point_index,
                    datetime.fromtimestamp(p.timestamp).isoformat(),
                    f"{p.setpoint:.6e}", f"{p.voltage:.6e}",
                    f"{p.current:.6e}", f"{p.optical_power:.6e}", p.status
                ])
    
    def _save_stress_step(self, data: List[StressPoint], stress_level: float):
        """Save stress data for a step"""
        if not data or not self.config.autosave or not self.session_folder:
            return
        
        filename = f"stress_step_{self.current_step:03d}_level_{stress_level:.4f}.csv"
        filepath = self.session_folder / filename
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Step", "Stress_Level", "Timestamp", "Elapsed_s",
                "Voltage_V", "Current_A", "Optical_Power_W", "Status"
            ])
            for p in data:
                writer.writerow([
                    p.step, f"{p.stress_level:.6e}",
                    datetime.fromtimestamp(p.timestamp).isoformat(),
                    f"{p.elapsed_s:.3f}", f"{p.voltage:.6e}",
                    f"{p.current:.6e}", f"{p.optical_power:.6e}", p.status
                ])
    
    def _save_summary(self):
        """Save step summaries"""
        if not self.step_summaries or not self.session_folder:
            return
        
        filepath = self.session_folder / "step_summary.csv"
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Step", "Stress_Level", "Timestamp", "Peak_Current_A", "Peak_Power_W",
                "Threshold_V", "Series_R_Ohm", "Stress_Avg_Current_A", "Stress_Avg_Power_W"
            ])
            for s in self.step_summaries:
                writer.writerow([
                    s.step, f"{s.stress_level:.6e}", s.timestamp,
                    f"{s.peak_current:.6e}", f"{s.peak_power:.6e}",
                    f"{s.threshold_voltage:.4f}", f"{s.series_resistance:.4f}",
                    f"{s.stress_avg_current:.6e}", f"{s.stress_avg_power:.6e}"
                ])
        
        self.log(f"Summary saved to: {filepath}")
    
    def stop(self):
        """Request stop of test"""
        self.stop_requested = True


# =============================================================================
# GUI Worker Thread
# =============================================================================

class TestWorker(QThread):
    """Worker thread for running the step stress test"""
    measurement_point = pyqtSignal(object)
    stress_point = pyqtSignal(object)
    phase_change = pyqtSignal(object)
    step_complete = pyqtSignal(int, float)
    progress = pyqtSignal(int, int)
    log_message = pyqtSignal(str)
    finished_signal = pyqtSignal()
    
    def __init__(self, engine: StepStressMeasurementEngine):
        super().__init__()
        self.engine = engine
        self.engine.on_measurement_point = lambda p: self.measurement_point.emit(p)
        self.engine.on_stress_point = lambda p: self.stress_point.emit(p)
        self.engine.on_phase_change = lambda p: self.phase_change.emit(p)
        self.engine.on_step_complete = lambda s, l: self.step_complete.emit(s, l)
        self.engine.on_progress = lambda c, t: self.progress.emit(c, t)
        self.engine.on_log = lambda m: self.log_message.emit(m)
    
    def run(self):
        self.engine.run()
        self.finished_signal.emit()


# =============================================================================
# Main GUI
# =============================================================================

class StepStressMeasurementGUI(QMainWindow):
    """Main GUI for step stress measurements"""
    
    def __init__(self):
        super().__init__()
        self.b1500 = B1500Controller()
        self.power_meter = ThorlabsPowerMeterController()
        self.worker = None
        
        self.setWindowTitle("B1500 Step Stress Measurement")
        self.setMinimumSize(1600, 1000)
        
        # Plot data
        self.meas_voltages = []
        self.meas_currents = []
        self.meas_powers = []
        self.meas_steps = []
        
        self.stress_times = []
        self.stress_currents = []
        self.stress_powers = []
        
        self.summary_steps = []
        self.summary_stress_levels = []
        self.summary_peak_currents = []
        self.summary_peak_powers = []
        
        self.setup_ui()
        self.refresh_resources()
    
    def setup_ui(self):
        """Setup the GUI layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel - controls with scroll
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumWidth(520)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # === Device Connection ===
        device_group = QGroupBox("Device Connection")
        device_layout = QGridLayout(device_group)
        
        device_layout.addWidget(QLabel("B1500:"), 0, 0)
        self.combo_b1500 = QComboBox()
        self.combo_b1500.setMinimumWidth(200)
        device_layout.addWidget(self.combo_b1500, 0, 1)
        
        self.btn_connect_b1500 = QPushButton("Connect")
        self.btn_connect_b1500.clicked.connect(self.connect_b1500)
        device_layout.addWidget(self.btn_connect_b1500, 0, 2)
        
        self.label_b1500_status = QLabel("Not connected")
        self.label_b1500_status.setStyleSheet("color: red;")
        device_layout.addWidget(self.label_b1500_status, 1, 0, 1, 3)
        
        device_layout.addWidget(QLabel("Power Meter:"), 2, 0)
        self.combo_power_meter = QComboBox()
        device_layout.addWidget(self.combo_power_meter, 2, 1)
        
        self.btn_connect_pm = QPushButton("Connect")
        self.btn_connect_pm.clicked.connect(self.connect_power_meter)
        device_layout.addWidget(self.btn_connect_pm, 2, 2)
        
        self.label_pm_status = QLabel("Not connected")
        self.label_pm_status.setStyleSheet("color: red;")
        device_layout.addWidget(self.label_pm_status, 3, 0, 1, 3)
        
        self.btn_refresh = QPushButton("Refresh Devices")
        self.btn_refresh.clicked.connect(self.refresh_resources)
        device_layout.addWidget(self.btn_refresh, 4, 0, 1, 3)
        
        left_layout.addWidget(device_group)
        
        # === Measurement Configuration ===
        meas_group = QGroupBox("IV Measurement Configuration")
        meas_layout = QGridLayout(meas_group)
        
        row = 0
        meas_layout.addWidget(QLabel("SMU:"), row, 0)
        self.spin_smu = QSpinBox()
        self.spin_smu.setRange(1, 10)
        self.spin_smu.setValue(1)
        meas_layout.addWidget(self.spin_smu, row, 1)
        
        meas_layout.addWidget(QLabel("Mode:"), row, 2)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["IV (V→I)", "VI (I→V)"])
        self.combo_mode.currentIndexChanged.connect(self.on_meas_mode_changed)
        meas_layout.addWidget(self.combo_mode, row, 3)
        
        row += 1
        meas_layout.addWidget(QLabel("Start:"), row, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(-200, 200)
        self.spin_start.setDecimals(4)
        self.spin_start.setValue(0)
        meas_layout.addWidget(self.spin_start, row, 1)
        
        meas_layout.addWidget(QLabel("Stop:"), row, 2)
        self.spin_stop = QDoubleSpinBox()
        self.spin_stop.setRange(-200, 200)
        self.spin_stop.setDecimals(4)
        self.spin_stop.setValue(2.0)
        meas_layout.addWidget(self.spin_stop, row, 3)
        
        row += 1
        meas_layout.addWidget(QLabel("Steps:"), row, 0)
        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(2, 1001)
        self.spin_steps.setValue(21)
        meas_layout.addWidget(self.spin_steps, row, 1)
        
        meas_layout.addWidget(QLabel("Dwell (s):"), row, 2)
        self.spin_dwell = QDoubleSpinBox()
        self.spin_dwell.setRange(0, 10)
        self.spin_dwell.setDecimals(3)
        self.spin_dwell.setValue(0.1)
        meas_layout.addWidget(self.spin_dwell, row, 3)
        
        row += 1
        meas_layout.addWidget(QLabel("Compliance:"), row, 0)
        self.spin_meas_compliance = QDoubleSpinBox()
        self.spin_meas_compliance.setRange(0.0001, 200)
        self.spin_meas_compliance.setDecimals(6)
        self.spin_meas_compliance.setValue(0.1)
        meas_layout.addWidget(self.spin_meas_compliance, row, 1, 1, 3)
        
        # Integration time for measurement (same style as b1500_powermeter_synchronized.py)
        row += 1
        meas_layout.addWidget(QLabel("Integration Mode:"), row, 0)
        self.combo_meas_integration_mode = QComboBox()
        self.combo_meas_integration_mode.addItems(["Auto", "PLC", "Manual"])
        self.combo_meas_integration_mode.setCurrentIndex(0)
        self.combo_meas_integration_mode.setToolTip(
            "Auto: Automatic integration time\n"
            "PLC: Power Line Cycle based (50/60Hz)\n"
            "Manual: Manual aperture time setting"
        )
        self.combo_meas_integration_mode.currentIndexChanged.connect(self.on_meas_integration_mode_changed)
        meas_layout.addWidget(self.combo_meas_integration_mode, row, 1)
        
        meas_layout.addWidget(QLabel("ADC Type:"), row, 2)
        self.combo_meas_adc_type = QComboBox()
        self.combo_meas_adc_type.addItems(["High-Speed", "High-Resolution"])
        self.combo_meas_adc_type.setCurrentIndex(0)
        self.combo_meas_adc_type.setToolTip(
            "High-Speed: Faster measurements, lower resolution\n"
            "High-Resolution: Slower but more accurate"
        )
        meas_layout.addWidget(self.combo_meas_adc_type, row, 3)
        
        row += 1
        meas_layout.addWidget(QLabel("N Value:"), row, 0)
        self.spin_meas_integration_n = QSpinBox()
        self.spin_meas_integration_n.setRange(1, 1023)
        self.spin_meas_integration_n.setValue(1)
        self.spin_meas_integration_n.setToolTip(
            "Auto mode: Number of averaging samples (1-1023)\n"
            "PLC mode: Number of power line cycles (1-1023)\n"
            "Manual mode: Not used (use aperture time instead)"
        )
        meas_layout.addWidget(self.spin_meas_integration_n, row, 1)
        
        meas_layout.addWidget(QLabel("Aperture (s):"), row, 2)
        self.spin_meas_aperture = QDoubleSpinBox()
        self.spin_meas_aperture.setRange(0.00001, 10.0)
        self.spin_meas_aperture.setDecimals(5)
        self.spin_meas_aperture.setValue(0.001)
        self.spin_meas_aperture.setEnabled(False)
        self.spin_meas_aperture.setToolTip(
            "Manual integration aperture time in seconds\n"
            "Range: 10µs to 10s\n"
            "Only used in Manual mode"
        )
        meas_layout.addWidget(self.spin_meas_aperture, row, 3)
        
        # Measurement range
        row += 1
        meas_layout.addWidget(QLabel("Meas Range:"), row, 0)
        self.combo_meas_range = QComboBox()
        self._populate_current_ranges(self.combo_meas_range)  # Default: IV mode measures current
        self.combo_meas_range.setCurrentIndex(0)
        self.combo_meas_range.setToolTip("Measurement range (Auto recommended for sweeps)")
        meas_layout.addWidget(self.combo_meas_range, row, 1, 1, 3)
        
        left_layout.addWidget(meas_group)
        
        # === Stress Configuration ===
        stress_group = QGroupBox("Step Stress Configuration")
        stress_layout = QGridLayout(stress_group)
        
        row = 0
        stress_layout.addWidget(QLabel("Stress Mode:"), row, 0)
        self.combo_stress_mode = QComboBox()
        self.combo_stress_mode.addItems(["Constant Voltage", "Constant Current"])
        self.combo_stress_mode.currentIndexChanged.connect(self.on_stress_mode_changed)
        stress_layout.addWidget(self.combo_stress_mode, row, 1, 1, 3)
        
        row += 1
        stress_layout.addWidget(QLabel("Start Level:"), row, 0)
        self.spin_stress_start = QDoubleSpinBox()
        self.spin_stress_start.setRange(-200, 200)
        self.spin_stress_start.setDecimals(4)
        self.spin_stress_start.setValue(2.0)
        self.spin_stress_start.setSuffix(" V")
        stress_layout.addWidget(self.spin_stress_start, row, 1)
        
        stress_layout.addWidget(QLabel("Stop Level:"), row, 2)
        self.spin_stress_stop = QDoubleSpinBox()
        self.spin_stress_stop.setRange(-200, 200)
        self.spin_stress_stop.setDecimals(4)
        self.spin_stress_stop.setValue(5.0)
        self.spin_stress_stop.setSuffix(" V")
        stress_layout.addWidget(self.spin_stress_stop, row, 3)
        
        row += 1
        stress_layout.addWidget(QLabel("Step Size:"), row, 0)
        self.spin_stress_step = QDoubleSpinBox()
        self.spin_stress_step.setRange(-100, 100)
        self.spin_stress_step.setDecimals(4)
        self.spin_stress_step.setValue(0.5)
        self.spin_stress_step.setSuffix(" V")
        stress_layout.addWidget(self.spin_stress_step, row, 1)
        
        stress_layout.addWidget(QLabel("Duration (s):"), row, 2)
        self.spin_stress_duration = QDoubleSpinBox()
        self.spin_stress_duration.setRange(1, 100000)
        self.spin_stress_duration.setDecimals(1)
        self.spin_stress_duration.setValue(60)
        stress_layout.addWidget(self.spin_stress_duration, row, 3)
        
        row += 1
        stress_layout.addWidget(QLabel("Sample Rate (s):"), row, 0)
        self.spin_stress_interval = QDoubleSpinBox()
        self.spin_stress_interval.setRange(0.1, 60)
        self.spin_stress_interval.setDecimals(2)
        self.spin_stress_interval.setValue(1.0)
        stress_layout.addWidget(self.spin_stress_interval, row, 1)
        
        stress_layout.addWidget(QLabel("Compliance:"), row, 2)
        self.spin_stress_compliance = QDoubleSpinBox()
        self.spin_stress_compliance.setRange(0.0001, 200)
        self.spin_stress_compliance.setDecimals(6)
        self.spin_stress_compliance.setValue(0.1)
        stress_layout.addWidget(self.spin_stress_compliance, row, 3)
        
        # Integration time for stress monitoring (same style as b1500_powermeter_synchronized.py)
        row += 1
        stress_layout.addWidget(QLabel("Integration Mode:"), row, 0)
        self.combo_stress_integration_mode = QComboBox()
        self.combo_stress_integration_mode.addItems(["Auto", "PLC", "Manual"])
        self.combo_stress_integration_mode.setCurrentIndex(0)
        self.combo_stress_integration_mode.setToolTip(
            "Auto: Automatic integration time\n"
            "PLC: Power Line Cycle based (50/60Hz)\n"
            "Manual: Manual aperture time setting"
        )
        self.combo_stress_integration_mode.currentIndexChanged.connect(self.on_stress_integration_mode_changed)
        stress_layout.addWidget(self.combo_stress_integration_mode, row, 1)
        
        stress_layout.addWidget(QLabel("ADC Type:"), row, 2)
        self.combo_stress_adc_type = QComboBox()
        self.combo_stress_adc_type.addItems(["High-Speed", "High-Resolution"])
        self.combo_stress_adc_type.setCurrentIndex(0)
        self.combo_stress_adc_type.setToolTip(
            "High-Speed: Faster measurements, lower resolution\n"
            "High-Resolution: Slower but more accurate"
        )
        stress_layout.addWidget(self.combo_stress_adc_type, row, 3)
        
        row += 1
        stress_layout.addWidget(QLabel("N Value:"), row, 0)
        self.spin_stress_integration_n = QSpinBox()
        self.spin_stress_integration_n.setRange(1, 1023)
        self.spin_stress_integration_n.setValue(1)
        self.spin_stress_integration_n.setToolTip(
            "Auto mode: Number of averaging samples (1-1023)\n"
            "PLC mode: Number of power line cycles (1-1023)\n"
            "Manual mode: Not used (use aperture time instead)"
        )
        stress_layout.addWidget(self.spin_stress_integration_n, row, 1)
        
        stress_layout.addWidget(QLabel("Aperture (s):"), row, 2)
        self.spin_stress_aperture = QDoubleSpinBox()
        self.spin_stress_aperture.setRange(0.00001, 10.0)
        self.spin_stress_aperture.setDecimals(5)
        self.spin_stress_aperture.setValue(0.001)
        self.spin_stress_aperture.setEnabled(False)
        self.spin_stress_aperture.setToolTip(
            "Manual integration aperture time in seconds\n"
            "Range: 10µs to 10s\n"
            "Only used in Manual mode"
        )
        stress_layout.addWidget(self.spin_stress_aperture, row, 3)
        
        # Stress measurement range
        row += 1
        stress_layout.addWidget(QLabel("Meas Range:"), row, 0)
        self.combo_stress_range = QComboBox()
        self._populate_current_ranges(self.combo_stress_range)  # Default: Constant V stress monitors current
        self.combo_stress_range.setCurrentIndex(0)
        self.combo_stress_range.setToolTip("Measurement range for stress monitoring")
        stress_layout.addWidget(self.combo_stress_range, row, 1, 1, 3)
        
        # Step count preview
        row += 1
        self.label_step_count = QLabel("Steps: 7")
        self.label_step_count.setStyleSheet("font-weight: bold; color: blue;")
        stress_layout.addWidget(self.label_step_count, row, 0, 1, 4)
        
        # Stop on compliance option
        row += 1
        self.check_stop_on_compliance = QCheckBox("Stop and move to next step when compliance is reached")
        self.check_stop_on_compliance.setChecked(False)
        self.check_stop_on_compliance.setToolTip(
            "If enabled, the stress phase will end early and proceed to\n"
            "the next measurement step when compliance limit is reached.\n"
            "Useful for detecting device degradation or breakdown."
        )
        stress_layout.addWidget(self.check_stop_on_compliance, row, 0, 1, 4)
        
        # Connect signals to update step count
        self.spin_stress_start.valueChanged.connect(self.update_step_count)
        self.spin_stress_stop.valueChanged.connect(self.update_step_count)
        self.spin_stress_step.valueChanged.connect(self.update_step_count)
        
        left_layout.addWidget(stress_group)
        
        # === Power Meter Config ===
        pm_group = QGroupBox("Power Meter")
        pm_layout = QGridLayout(pm_group)
        
        self.check_enable_pm = QCheckBox("Enable Power Measurement")
        self.check_enable_pm.setChecked(True)
        pm_layout.addWidget(self.check_enable_pm, 0, 0, 1, 2)
        
        pm_layout.addWidget(QLabel("Wavelength (nm):"), 1, 0)
        self.spin_wavelength = QDoubleSpinBox()
        self.spin_wavelength.setRange(200, 2000)
        self.spin_wavelength.setValue(850)
        pm_layout.addWidget(self.spin_wavelength, 1, 1)
        
        left_layout.addWidget(pm_group)
        
        # === Output Configuration ===
        output_group = QGroupBox("Output")
        output_layout = QGridLayout(output_group)
        
        output_layout.addWidget(QLabel("Folder:"), 0, 0)
        self.edit_folder = QLineEdit(str(Path(__file__).parent / "results"))
        output_layout.addWidget(self.edit_folder, 0, 1)
        
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.browse_folder)
        output_layout.addWidget(self.btn_browse, 0, 2)
        
        output_layout.addWidget(QLabel("Device Name:"), 1, 0)
        self.edit_device_name = QLineEdit("Device_001")
        output_layout.addWidget(self.edit_device_name, 1, 1, 1, 2)
        
        self.check_autosave = QCheckBox("Autosave Data")
        self.check_autosave.setChecked(True)
        output_layout.addWidget(self.check_autosave, 2, 0, 1, 3)
        
        self.check_initial_meas = QCheckBox("Initial Measurement (Baseline)")
        self.check_initial_meas.setChecked(True)
        output_layout.addWidget(self.check_initial_meas, 3, 0, 1, 3)
        
        left_layout.addWidget(output_group)
        
        # === Control Buttons ===
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("▶ Start Step Stress Test")
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_test)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("font-size: 14px;")
        self.btn_stop.clicked.connect(self.stop_test)
        btn_layout.addWidget(self.btn_stop)
        
        left_layout.addLayout(btn_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        
        # Status label
        self.label_phase = QLabel("Phase: IDLE")
        self.label_phase.setStyleSheet("font-weight: bold; font-size: 12px;")
        left_layout.addWidget(self.label_phase)
        
        self.label_current_step = QLabel("Current Step: -")
        self.label_current_step.setStyleSheet("font-size: 11px;")
        left_layout.addWidget(self.label_current_step)
        
        # Log
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)
        left_layout.addWidget(log_group)
        
        left_layout.addStretch()
        
        scroll_area.setWidget(left_panel)
        main_layout.addWidget(scroll_area)
        
        # === Right Panel - Plots ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Create tabs
        self.tab_widget = QTabWidget()
        
        # Tab 1: Live Plots
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        
        self.figure = Figure(figsize=(12, 9))
        self.canvas = FigureCanvas(self.figure)
        
        # Create 2x2 subplot grid
        self.ax_iv = self.figure.add_subplot(2, 2, 1)
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title("I-V Characteristic")
        self.ax_iv.grid(True, alpha=0.3)
        
        self.ax_li = self.figure.add_subplot(2, 2, 2)
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title("L-I Characteristic")
        self.ax_li.grid(True, alpha=0.3)
        
        self.ax_stress = self.figure.add_subplot(2, 2, 3)
        self.ax_stress.set_xlabel("Time (s)")
        self.ax_stress.set_ylabel("Current (A) / Power (W)")
        self.ax_stress.set_title("Stress Monitoring")
        self.ax_stress.grid(True, alpha=0.3)
        
        self.ax_degradation = self.figure.add_subplot(2, 2, 4)
        self.ax_degradation.set_xlabel("Stress Level")
        self.ax_degradation.set_ylabel("Peak Values")
        self.ax_degradation.set_title("Degradation vs Stress Level")
        self.ax_degradation.grid(True, alpha=0.3)
        
        self.figure.tight_layout()
        plot_layout.addWidget(self.canvas)
        
        self.tab_widget.addTab(plot_tab, "Live Plots")
        
        # Tab 2: Summary Table
        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(8)
        self.summary_table.setHorizontalHeaderLabels([
            "Step", "Stress Level", "Peak Current (A)", "Peak Power (W)",
            "Threshold V", "Series R (Ω)", "Stress Avg I", "Stress Avg P"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.summary_table)
        
        self.tab_widget.addTab(table_tab, "Step Summary")
        
        # Tab 3: All IV curves
        all_iv_tab = QWidget()
        all_iv_layout = QVBoxLayout(all_iv_tab)
        
        self.figure_all_iv = Figure(figsize=(10, 8))
        self.canvas_all_iv = FigureCanvas(self.figure_all_iv)
        
        self.ax_all_iv = self.figure_all_iv.add_subplot(1, 1, 1)
        self.ax_all_iv.set_xlabel("Voltage (V)")
        self.ax_all_iv.set_ylabel("Current (A)")
        self.ax_all_iv.set_title("All IV Curves (Color = Stress Level)")
        self.ax_all_iv.grid(True, alpha=0.3)
        
        all_iv_layout.addWidget(self.canvas_all_iv)
        self.tab_widget.addTab(all_iv_tab, "All IV Curves")
        
        right_layout.addWidget(self.tab_widget)
        main_layout.addWidget(right_panel, stretch=2)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Initialize step count
        self.update_step_count()
    
    def log(self, message: str):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def refresh_resources(self):
        self.combo_b1500.clear()
        self.combo_power_meter.clear()
        
        all_resources = self.b1500.list_all_resources()
        
        gpib_resources = [r for r in all_resources if "GPIB" in r.upper()]
        self.combo_b1500.addItems(gpib_resources)
        
        usb_resources = [r for r in all_resources if "USB" in r.upper()]
        self.combo_power_meter.addItems(usb_resources)
        
        self.log(f"Found {len(gpib_resources)} GPIB and {len(usb_resources)} USB resources")
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.edit_folder.setText(folder)
    
    def update_step_count(self):
        """Update the step count preview label"""
        start = self.spin_stress_start.value()
        stop = self.spin_stress_stop.value()
        step = self.spin_stress_step.value()
        
        if step == 0:
            count = 1
        elif step > 0:
            count = int((stop - start) / step) + 1
        else:
            count = int((start - stop) / abs(step)) + 1
        
        count = max(1, count)
        self.label_step_count.setText(f"Total stress steps: {count}")
    
    def on_meas_mode_changed(self, index: int):
        """Handle measurement mode change - update range units.
        
        IV mode (index=0): Source voltage, measure current -> current ranges
        VI mode (index=1): Source current, measure voltage -> voltage ranges
        """
        if index == 0:  # IV mode - measure current
            self._populate_current_ranges(self.combo_meas_range)
        else:  # VI mode - measure voltage
            self._populate_voltage_ranges(self.combo_meas_range)
    
    def on_stress_mode_changed(self, index: int):
        """Handle stress mode change - update suffix and range units.
        
        Constant Voltage (index=0): Monitor current -> current ranges
        Constant Current (index=1): Monitor voltage -> voltage ranges
        """
        suffix = " V" if index == 0 else " A"
        self.spin_stress_start.setSuffix(suffix)
        self.spin_stress_stop.setSuffix(suffix)
        self.spin_stress_step.setSuffix(suffix)
        
        # Update measurement range options based on what we're monitoring
        if index == 0:  # Constant Voltage - monitor current
            self._populate_current_ranges(self.combo_stress_range)
        else:  # Constant Current - monitor voltage
            self._populate_voltage_ranges(self.combo_stress_range)
    
    def _populate_current_ranges(self, combo: QComboBox):
        """Populate combo box with current measurement ranges."""
        combo.clear()
        combo.addItems([
            "Auto", "1 pA", "10 pA", "100 pA", "1 nA", "10 nA", "100 nA",
            "1 µA", "10 µA", "100 µA", "1 mA", "10 mA", "100 mA", "200 mA", "1 A"
        ])
    
    def _populate_voltage_ranges(self, combo: QComboBox):
        """Populate combo box with voltage measurement ranges."""
        combo.clear()
        combo.addItems([
            "Auto", "0.5 V", "2 V", "5 V", "20 V", "40 V", "100 V", "200 V"
        ])
    
    def on_meas_integration_mode_changed(self, index: int):
        """Handle measurement integration mode change."""
        mode = self.combo_meas_integration_mode.currentText()
        # Enable/disable appropriate controls based on mode
        if mode == "Manual":
            self.spin_meas_aperture.setEnabled(True)
            self.spin_meas_integration_n.setEnabled(False)
            self.combo_meas_adc_type.setEnabled(False)
        else:
            self.spin_meas_aperture.setEnabled(False)
            self.spin_meas_integration_n.setEnabled(True)
            self.combo_meas_adc_type.setEnabled(mode == "Auto")
    
    def on_stress_integration_mode_changed(self, index: int):
        """Handle stress integration mode change."""
        mode = self.combo_stress_integration_mode.currentText()
        # Enable/disable appropriate controls based on mode
        if mode == "Manual":
            self.spin_stress_aperture.setEnabled(True)
            self.spin_stress_integration_n.setEnabled(False)
            self.combo_stress_adc_type.setEnabled(False)
        else:
            self.spin_stress_aperture.setEnabled(False)
            self.spin_stress_integration_n.setEnabled(True)
            self.combo_stress_adc_type.setEnabled(mode == "Auto")
    
    def _build_integration_time_string(self, mode: str, adc_type: str, n_value: int, aperture: float) -> str:
        """Build integration time string from GUI settings."""
        if mode == "Auto":
            # AUTO_SHORT or AUTO_LONG based on ADC type, with N value
            adc_suffix = "SHORT" if adc_type == "High-Speed" else "LONG"
            return f"AUTO_{adc_suffix}_{n_value}"
        elif mode == "PLC":
            return f"PLC_{n_value}"
        else:  # Manual
            return f"MANUAL_{aperture}"
    
    def _get_meas_range_value(self, combo: QComboBox) -> Optional[float]:
        """Convert range combo selection to range value for B1500."""
        range_text = combo.currentText()
        if range_text == "Auto":
            return None  # Auto range
        
        # Current ranges
        current_range_map = {
            "1 pA": 1e-12, "10 pA": 10e-12, "100 pA": 100e-12,
            "1 nA": 1e-9, "10 nA": 10e-9, "100 nA": 100e-9,
            "1 µA": 1e-6, "10 µA": 10e-6, "100 µA": 100e-6,
            "1 mA": 1e-3, "10 mA": 10e-3, "100 mA": 100e-3, "200 mA": 200e-3,
            "1 A": 1.0
        }
        
        # Voltage ranges
        voltage_range_map = {
            "0.5 V": 0.5, "2 V": 2.0, "5 V": 5.0, "20 V": 20.0,
            "40 V": 40.0, "100 V": 100.0, "200 V": 200.0
        }
        
        # Check both maps
        if range_text in current_range_map:
            return current_range_map[range_text]
        elif range_text in voltage_range_map:
            return voltage_range_map[range_text]
        return None
    
    def connect_b1500(self):
        if self.b1500.connected:
            self.b1500.disconnect()
            self.label_b1500_status.setText("Not connected")
            self.label_b1500_status.setStyleSheet("color: red;")
            self.btn_connect_b1500.setText("Connect")
            self.log("B1500 disconnected")
        else:
            resource = self.combo_b1500.currentText()
            if not resource:
                QMessageBox.warning(self, "Error", "No B1500 resource selected")
                return
            
            success, msg = self.b1500.connect(resource)
            if success:
                self.label_b1500_status.setText(f"Connected: {self.b1500.idn[:40]}...")
                self.label_b1500_status.setStyleSheet("color: green;")
                self.btn_connect_b1500.setText("Disconnect")
                self.log(f"B1500 connected: {self.b1500.idn}")
            else:
                QMessageBox.warning(self, "Connection Failed", msg)
    
    def connect_power_meter(self):
        if self.power_meter.connected:
            self.power_meter.disconnect()
            self.label_pm_status.setText("Not connected")
            self.label_pm_status.setStyleSheet("color: red;")
            self.btn_connect_pm.setText("Connect")
            self.log("Power meter disconnected")
        else:
            resource = self.combo_power_meter.currentText()
            if not resource:
                QMessageBox.warning(self, "Error", "No power meter resource selected")
                return
            
            success, msg = self.power_meter.connect(resource)
            if success:
                self.label_pm_status.setText(f"Connected: {self.power_meter.idn[:40]}...")
                self.label_pm_status.setStyleSheet("color: green;")
                self.btn_connect_pm.setText("Disconnect")
                self.log(f"Power meter connected: {self.power_meter.idn}")
            else:
                QMessageBox.warning(self, "Connection Failed", msg)
    
    def get_config(self) -> StepStressConfig:
        mode = "iv" if self.combo_mode.currentIndex() == 0 else "vi"
        stress_mode = "voltage" if self.combo_stress_mode.currentIndex() == 0 else "current"
        
        # Build integration time strings from new GUI controls
        meas_integration_time = self._build_integration_time_string(
            self.combo_meas_integration_mode.currentText(),
            self.combo_meas_adc_type.currentText(),
            self.spin_meas_integration_n.value(),
            self.spin_meas_aperture.value()
        )
        
        stress_integration_time = self._build_integration_time_string(
            self.combo_stress_integration_mode.currentText(),
            self.combo_stress_adc_type.currentText(),
            self.spin_stress_integration_n.value(),
            self.spin_stress_aperture.value()
        )
        
        # Get measurement ranges
        meas_range = self._get_meas_range_value(self.combo_meas_range)
        stress_range = self._get_meas_range_value(self.combo_stress_range)
        
        return StepStressConfig(
            measurement=MeasurementSettings(
                smu=self.spin_smu.value(),
                mode=mode,
                start=self.spin_start.value(),
                stop=self.spin_stop.value(),
                steps=self.spin_steps.value(),
                dwell_s=self.spin_dwell.value(),
                compliance=self.spin_meas_compliance.value(),
                integration_time=meas_integration_time,
                meas_range=meas_range
            ),
            stress=StressSettings(
                mode=stress_mode,
                start_value=self.spin_stress_start.value(),
                stop_value=self.spin_stress_stop.value(),
                step_value=self.spin_stress_step.value(),
                duration_s=self.spin_stress_duration.value(),
                sample_interval_s=self.spin_stress_interval.value(),
                compliance=self.spin_stress_compliance.value(),
                integration_time=stress_integration_time,
                meas_range=stress_range,
                stop_on_compliance=self.check_stop_on_compliance.isChecked()
            ),
            initial_measurement=self.check_initial_meas.isChecked(),
            enable_power_meter=self.check_enable_pm.isChecked(),
            power_wavelength_nm=self.spin_wavelength.value(),
            output_folder=self.edit_folder.text(),
            device_name=self.edit_device_name.text(),
            autosave=self.check_autosave.isChecked()
        )
    
    def start_test(self):
        if not self.b1500.connected and not self.power_meter.connected:
            QMessageBox.warning(self, "Error", "No devices connected")
            return
        
        # Clear data
        self.meas_voltages = []
        self.meas_currents = []
        self.meas_powers = []
        self.meas_steps = []
        self.stress_times = []
        self.stress_currents = []
        self.stress_powers = []
        self.summary_steps = []
        self.summary_stress_levels = []
        self.summary_peak_currents = []
        self.summary_peak_powers = []
        
        self.summary_table.setRowCount(0)
        self.update_plots()
        self.update_all_iv_plot()
        
        config = self.get_config()
        engine = StepStressMeasurementEngine(self.b1500, self.power_meter, config)
        
        self.worker = TestWorker(engine)
        self.worker.measurement_point.connect(self.on_measurement_point)
        self.worker.stress_point.connect(self.on_stress_point)
        self.worker.phase_change.connect(self.on_phase_change)
        self.worker.step_complete.connect(self.on_step_complete)
        self.worker.progress.connect(self.on_progress)
        self.worker.log_message.connect(self.log)
        self.worker.finished_signal.connect(self.on_test_complete)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def stop_test(self):
        if self.worker and self.worker.engine:
            self.worker.engine.stop()
            self.log("Stop requested...")
    
    def on_measurement_point(self, point: MeasurementPoint):
        self.meas_voltages.append(point.voltage)
        self.meas_currents.append(point.current)
        self.meas_powers.append(point.optical_power)
        self.meas_steps.append(point.step)
        self.update_measurement_plots()
    
    def on_stress_point(self, point: StressPoint):
        self.stress_times.append(point.elapsed_s)
        self.stress_currents.append(point.current)
        self.stress_powers.append(point.optical_power)
        
        if len(self.stress_times) % 5 == 0:
            self.update_stress_plot()
    
    def on_phase_change(self, phase: TestPhase):
        phase_colors = {
            TestPhase.IDLE: "gray",
            TestPhase.MEASUREMENT: "blue",
            TestPhase.STRESS: "orange",
            TestPhase.COMPLETED: "green",
            TestPhase.STOPPED: "red"
        }
        color = phase_colors.get(phase, "black")
        self.label_phase.setText(f"Phase: {phase.value.upper()}")
        self.label_phase.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {color};")
        
        if phase == TestPhase.STRESS:
            self.stress_times = []
            self.stress_currents = []
            self.stress_powers = []
    
    def on_step_complete(self, step: int, stress_level: float):
        self.label_current_step.setText(f"Completed Step {step}, Stress: {stress_level:.4f}")
        
        # Update all IV curves plot
        self.update_all_iv_plot()
        
        # Add to summary table
        if self.worker and self.worker.engine.step_summaries:
            summary = self.worker.engine.step_summaries[-1]
            
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
            self.summary_table.setItem(row, 0, QTableWidgetItem(str(summary.step)))
            self.summary_table.setItem(row, 1, QTableWidgetItem(f"{summary.stress_level:.4f}"))
            self.summary_table.setItem(row, 2, QTableWidgetItem(f"{summary.peak_current:.4e}"))
            self.summary_table.setItem(row, 3, QTableWidgetItem(f"{summary.peak_power:.4e}"))
            self.summary_table.setItem(row, 4, QTableWidgetItem(f"{summary.threshold_voltage:.4f}"))
            self.summary_table.setItem(row, 5, QTableWidgetItem(f"{summary.series_resistance:.2f}"))
            self.summary_table.setItem(row, 6, QTableWidgetItem(f"{summary.stress_avg_current:.4e}"))
            self.summary_table.setItem(row, 7, QTableWidgetItem(f"{summary.stress_avg_power:.4e}"))
            
            self.summary_steps.append(summary.step)
            self.summary_stress_levels.append(summary.stress_level)
            self.summary_peak_currents.append(summary.peak_current)
            self.summary_peak_powers.append(summary.peak_power)
            
            self.update_degradation_plot()
    
    def on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(f"Step {current}/{total}")
    
    def on_test_complete(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_bar.showMessage("Test complete")
        self.log("=" * 50)
        self.log("STEP STRESS TEST COMPLETED")
        self.update_all_iv_plot()
    
    def update_measurement_plots(self):
        if not self.meas_voltages:
            return
        
        current_step = self.meas_steps[-1] if self.meas_steps else 0
        step_mask = [s == current_step for s in self.meas_steps]
        
        v_step = [v for v, m in zip(self.meas_voltages, step_mask) if m]
        i_step = [i for i, m in zip(self.meas_currents, step_mask) if m]
        p_step = [p for p, m in zip(self.meas_powers, step_mask) if m]
        
        # IV plot
        self.ax_iv.clear()
        self.ax_iv.plot(v_step, i_step, 'b.-', linewidth=1, markersize=3)
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title(f"I-V Characteristic (Step {current_step})")
        self.ax_iv.grid(True, alpha=0.3)
        
        # LI plot
        self.ax_li.clear()
        self.ax_li.plot(i_step, p_step, 'r.-', linewidth=1, markersize=3)
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title(f"L-I Characteristic (Step {current_step})")
        self.ax_li.grid(True, alpha=0.3)
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def update_stress_plot(self):
        if not self.stress_times:
            return
        
        self.ax_stress.clear()
        
        ax1 = self.ax_stress
        ax2 = ax1.twinx()
        
        line1, = ax1.plot(self.stress_times, self.stress_currents, 'b-', 
                         linewidth=1, label='Current')
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("Current (A)", color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        
        line2, = ax2.plot(self.stress_times, self.stress_powers, 'r-', 
                         linewidth=1, label='Power')
        ax2.set_ylabel("Optical Power (W)", color='red')
        ax2.tick_params(axis='y', labelcolor='red')
        
        ax1.set_title("Stress Monitoring")
        ax1.grid(True, alpha=0.3)
        ax1.legend([line1, line2], ['Current', 'Power'], loc='upper right')
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def update_degradation_plot(self):
        if not self.summary_stress_levels:
            return
        
        self.ax_degradation.clear()
        
        ax1 = self.ax_degradation
        ax2 = ax1.twinx()
        
        line1, = ax1.plot(self.summary_stress_levels, self.summary_peak_currents, 'bo-', 
                         markersize=6, label='Peak Current')
        ax1.set_xlabel("Stress Level (V/A)")
        ax1.set_ylabel("Peak Current (A)", color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        
        line2, = ax2.plot(self.summary_stress_levels, self.summary_peak_powers, 'rs-', 
                         markersize=6, label='Peak Power')
        ax2.set_ylabel("Peak Power (W)", color='red')
        ax2.tick_params(axis='y', labelcolor='red')
        
        ax1.set_title("Degradation vs Stress Level")
        ax1.grid(True, alpha=0.3)
        ax1.legend([line1, line2], ['Peak Current', 'Peak Power'], loc='upper right')
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def update_all_iv_plot(self):
        """Update the all IV curves plot with color coding by stress level"""
        self.ax_all_iv.clear()
        
        if not self.meas_voltages:
            self.ax_all_iv.set_xlabel("Voltage (V)")
            self.ax_all_iv.set_ylabel("Current (A)")
            self.ax_all_iv.set_title("All IV Curves (Color = Stress Level)")
            self.ax_all_iv.grid(True, alpha=0.3)
            self.canvas_all_iv.draw()
            return
        
        # Get unique steps
        unique_steps = sorted(set(self.meas_steps))
        
        # Color map
        cmap = plt.cm.viridis
        colors = [cmap(i / max(1, len(unique_steps) - 1)) for i in range(len(unique_steps))]
        
        for idx, step in enumerate(unique_steps):
            step_mask = [s == step for s in self.meas_steps]
            v_step = [v for v, m in zip(self.meas_voltages, step_mask) if m]
            i_step = [i for i, m in zip(self.meas_currents, step_mask) if m]
            
            if v_step:
                # Get stress level for this step from summaries
                stress_label = f"Step {step}"
                if self.worker and self.worker.engine.step_summaries:
                    for s in self.worker.engine.step_summaries:
                        if s.step == step:
                            stress_label = f"{s.stress_level:.2f}V"
                            break
                
                self.ax_all_iv.plot(v_step, i_step, '-', color=colors[idx], 
                                   linewidth=1.5, label=stress_label)
        
        self.ax_all_iv.set_xlabel("Voltage (V)")
        self.ax_all_iv.set_ylabel("Current (A)")
        self.ax_all_iv.set_title("All IV Curves (Color = Stress Level)")
        self.ax_all_iv.grid(True, alpha=0.3)
        
        if len(unique_steps) <= 15:
            self.ax_all_iv.legend(loc='best', fontsize=8)
        
        self.figure_all_iv.tight_layout()
        self.canvas_all_iv.draw()
    
    def update_plots(self):
        self.ax_iv.clear()
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title("I-V Characteristic")
        self.ax_iv.grid(True, alpha=0.3)
        
        self.ax_li.clear()
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title("L-I Characteristic")
        self.ax_li.grid(True, alpha=0.3)
        
        self.ax_stress.clear()
        self.ax_stress.set_xlabel("Time (s)")
        self.ax_stress.set_ylabel("Current / Power")
        self.ax_stress.set_title("Stress Monitoring")
        self.ax_stress.grid(True, alpha=0.3)
        
        self.ax_degradation.clear()
        self.ax_degradation.set_xlabel("Stress Level")
        self.ax_degradation.set_ylabel("Peak Values")
        self.ax_degradation.set_title("Degradation vs Stress Level")
        self.ax_degradation.grid(True, alpha=0.3)
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.stop_test()
            self.worker.wait(2000)
        
        self.b1500.disconnect()
        self.power_meter.disconnect()
        event.accept()


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="B1500 + Power Meter Step Stress Measurement"
    )
    parser.add_argument('--cli', action='store_true', help='Run in CLI mode (not implemented)')
    
    args = parser.parse_args()
    
    if args.cli:
        print("CLI mode not implemented yet. Please use GUI mode.")
        return
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StepStressMeasurementGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
