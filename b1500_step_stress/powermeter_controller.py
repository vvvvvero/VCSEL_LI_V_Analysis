#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
powermeter_controller.py
========================
Thread-safe VISA driver for Thorlabs PM100D / PM400 optical power meters.

The ThorlabsPowerMeterController class handles:
  - Device discovery via VISA resource manager
  - SCPI command sequencing (IDN, configuration, measurement)
  - Thread-safe concurrent access (internal lock)
  - Connection state management

© Veronica Gao Zhan – August 2026
"""

import time
import threading
from typing import List, Tuple, Optional

try:
    import pyvisa
    from pyvisa.errors import VisaIOError
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False


class ThorlabsPowerMeterController:
    """
    Thread-safe controller for Thorlabs PM100D/PM400 power meters.
    
    Example usage
    ─────────────
    >>> pm = ThorlabsPowerMeterController()
    >>> resources = pm.list_resources()
    >>> pm.connect(resources[0])
    >>> pm.configure(wavelength_nm=850.0)
    >>> power, status = pm.measure_power()
    >>> pm.disconnect()
    """
    
    # SCPI command constants
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
        """Create VISA resource manager, fallback to PyVISA backend if needed"""
        try:
            return pyvisa.ResourceManager()
        except Exception:
            return pyvisa.ResourceManager("@py")
    
    def list_resources(self, filter_pattern: str = "") -> List[str]:
        """
        List available VISA resources.
        
        Args
        ────
        filter_pattern : str, optional
            If provided, only resources containing this string (case-insensitive)
            are returned. For example, "GPIB" or "USB".
        
        Returns
        ───────
        List[str]
            Sorted list of VISA resource strings.
        """
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
        """
        Connect to power meter at given VISA resource address.
        
        Args
        ────
        resource : str
            VISA resource string (e.g., "USB0::0x1313::0x8078::P1234567::INSTR").
        timeout_ms : int, optional
            VISA operation timeout in milliseconds. Default: 5000.
        
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
        """Close connection to power meter and release resources"""
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
        """
        Configure power meter measurement parameters.
        
        Args
        ────
        wavelength_nm : float
            Centre wavelength for responsivity correction (nm). Typical: 850, 980, 1310, 1550.
        auto_range : bool, optional
            If True, enable auto-ranging. Default: True.
        averages : int, optional
            Number of hardware averages per measurement. Default: 1.
        
        Returns
        ───────
        bool
            True if successful.
        """
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
        """
        Measure optical power once.
        
        Returns
        ───────
        Tuple[float, str]
            (power_in_watts, status_string). On error, power is 0.0.
        
        Examples
        ────────
        >>> power, status = pm.measure_power()
        >>> print(f"{power:.3e} W")
        """
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
