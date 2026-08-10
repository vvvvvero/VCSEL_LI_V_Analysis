#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
b1500_controller.py
===================
Thread-safe VISA driver for Keysight B1500 Semiconductor Parameter Analyzer.

The B1500Controller class handles:
  - Device discovery and connection management
  - SMU configuration (measurement range, integration time, compliance)
  - Point-by-point sourcing and measurement
  - Response parsing and error handling
  - Thread-safe concurrent access

© Veronica Gao Zhan – August 2026
"""

import time
import threading
from typing import List, Tuple, Optional

from .config import MeasurementSettings, StressSettings

try:
    import pyvisa
    from pyvisa.errors import VisaIOError
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False


class B1500Controller:
    """
    Thread-safe controller for Keysight B1500 Semiconductor Parameter Analyzer.
    
    Supports:
      - IV and VI (reverse) sweep modes
      - Point-by-point sourcing
      - Stress monitoring with optical power readout
      - Integration time control (auto ADC, PLC, manual aperture)
    
    Example usage
    ─────────────
    >>> b1500 = B1500Controller()
    >>> resources = b1500.list_all_resources()
    >>> b1500.connect(resources[0])
    >>> cfg = MeasurementSettings(mode="iv", start=0, stop=2.0, steps=21)
    >>> b1500.configure_for_measurement(cfg)
    >>> for v_set in cfg.setpoints:
    ...     v_meas, i_meas = b1500.set_bias_and_measure(1, v_set, "iv", 0.1)
    >>> b1500.output_off(1)
    >>> b1500.disconnect()
    """
    
    def __init__(self):
        self.rm = None
        self.inst = None
        self.resource: Optional[str] = None
        self.idn: str = ""
        self.lock = threading.Lock()
        self.connected = False
    
    def _resource_manager(self):
        """Create VISA resource manager, fallback to PyVISA backend if needed"""
        try:
            return pyvisa.ResourceManager()
        except Exception:
            return pyvisa.ResourceManager("@py")
    
    def list_all_resources(self) -> List[str]:
        """
        List all available VISA resources.
        
        Returns
        ───────
        List[str]
            Sorted list of VISA resource strings.
        """
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
        """
        Connect to B1500 at given VISA resource address.
        
        Args
        ────
        resource : str
            VISA resource string (e.g., "GPIB0::17::INSTR").
        timeout_ms : int, optional
            VISA operation timeout in milliseconds. Default: 15000.
        
        Returns
        ───────
        Tuple[bool, str]
            (success, message). On success, message is the instrument IDN.
        """
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
        """Close connection to B1500 and release resources"""
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
        """Read response with graceful fallback encoding"""
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
        """
        Set integration time for measurement on specified SMU.
        
        Args
        ────
        smu : int
            SMU channel number.
        integration : str
            Integration time string. Supports:
            - "AUTO_SHORT_N" or "AUTO_LONG_N" for auto ADC
            - "PLC_N" for power line cycle based
            - "MANUAL_aperture" for manual aperture time
            - "SHORT", "MEDIUM", "LONG" for simple modes
        
        Examples
        ────────
        >>> b1500.set_integration_time(1, "AUTO_SHORT_1")
        >>> b1500.set_integration_time(1, "PLC_2")
        >>> b1500.set_integration_time(1, "MANUAL_0.001")
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
        """
        Configure B1500 for IV measurement phase.
        
        Args
        ────
        settings : MeasurementSettings
            Measurement configuration object.
        """
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
        """
        Configure B1500 for stress monitoring phase.
        
        Args
        ────
        smu : int
            SMU channel number.
        settings : StressSettings
            Stress configuration object.
        """
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
        """
        Set source bias and perform single-point measurement.
        
        Args
        ────
        smu : int
            SMU channel number.
        set_value : float
            Setpoint value (V in IV mode, A in VI mode).
        mode : str
            Measurement mode: "iv" (source V, measure I), "vi" (source I, measure V),
            "voltage" or "current" for stress monitoring.
        compliance : float
            Compliance limit.
        dwell_s : float, optional
            Dwell time before measurement (seconds). Default: 0.1.
        
        Returns
        ───────
        Tuple[float, float]
            (voltage, current) measured values. Missing values are 0.0.
        """
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
        """
        Turn off SMU output (set to 0V with small compliance).
        
        Args
        ────
        smu : int
            SMU channel number.
        """
        if not self.inst:
            return
        with self.lock:
            try:
                self.inst.write(f"DV {smu},0,0,0.01")
                time.sleep(0.05)
                self.inst.write(f"CL {smu}")
            except:
                pass
