#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
engine.py
=========
Step stress measurement engine (no GUI dependency).

The StepStressMeasurementEngine class orchestrates:
  - Configuration management
  - Device control (B1500, power meter)
  - Test flow (stress steps, IV measurements)
  - Data collection and export
  - Callback interface for progress updates

© Veronica Gao Zhan – August 2026
"""

import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Callable

import numpy as np

from .config import (
    TestPhase, MeasurementSettings, StressSettings, StepStressConfig,
    MeasurementPoint, StressPoint, StepSummary
)
from .b1500_controller import B1500Controller
from .powermeter_controller import ThorlabsPowerMeterController


class StepStressMeasurementEngine:
    """
    Orchestrates step stress measurement workflow.
    
    Flow:
      1. [Optional] Initial IV measurement (step 0, no stress)
      2. For each stress level:
         a. Apply stress and monitor for duration
         b. Remove stress
         c. Perform IV + optical power measurement
         d. Save data and calculate summary statistics
      3. Compile results and export
    
    Supports callbacks for progress reporting to GUI or CLI.
    
    Example usage
    ─────────────
    >>> b1500 = B1500Controller()
    >>> b1500.connect("GPIB0::17::INSTR")
    >>> pm = ThorlabsPowerMeterController()
    >>> pm.connect("USB0::0x1313::0x8078::P1234567::INSTR")
    >>> 
    >>> cfg = StepStressConfig(
    ...     measurement=MeasurementSettings(steps=21, start=0, stop=2.0),
    ...     stress=StressSettings(mode="voltage", start_value=2.0, stop_value=5.0, step_value=0.5)
    ... )
    >>> 
    >>> engine = StepStressMeasurementEngine(b1500, pm, cfg)
    >>> engine.on_log = print  # Connect callbacks
    >>> engine.on_progress = lambda c, t: print(f"{c}/{t}")
    >>> 
    >>> meas_data, stress_data = engine.run()
    """
    
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
        
        # Callbacks (type hints below)
        self.on_measurement_point: Optional[Callable[[MeasurementPoint], None]] = None
        self.on_stress_point: Optional[Callable[[StressPoint], None]] = None
        self.on_phase_change: Optional[Callable[[TestPhase], None]] = None
        self.on_step_complete: Optional[Callable[[int, float], None]] = None
        self.on_progress: Optional[Callable[[int, int], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        
        # Output
        self.session_folder: Optional[Path] = None
    
    def log(self, message: str):
        """Log message with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{timestamp}] {message}"
        print(msg)
        if self.on_log:
            self.on_log(msg)
    
    def set_phase(self, phase: TestPhase):
        """Update current phase and notify listeners"""
        self.current_phase = phase
        if self.on_phase_change:
            self.on_phase_change(phase)
    
    def run(self) -> Tuple[List[MeasurementPoint], List[StressPoint]]:
        """
        Run the complete step stress test.
        
        Returns
        ───────
        Tuple[List[MeasurementPoint], List[StressPoint]]
            All measurement and stress data collected.
        """
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
                    if abs(current) >= abs(cfg.compliance) * 0.99:
                        compliance_reached = True
                else:
                    if abs(voltage) >= abs(cfg.compliance) * 0.99:
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
        """Save measurement data for a step to CSV"""
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
        """Save stress data for a step to CSV"""
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
        """Save step summaries to CSV"""
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
        """Request immediate stop of the test"""
        self.stop_requested = True
