#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
__main__.py
===========
Entry point for command-line usage: python -m b1500_step_stress

© Veronica Gao Zhan – August 2026
"""

import argparse
import sys
from pathlib import Path

from .config import StepStressConfig, MeasurementSettings, StressSettings
from .b1500_controller import B1500Controller
from .powermeter_controller import ThorlabsPowerMeterController
from .engine import StepStressMeasurementEngine


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser"""
    parser = argparse.ArgumentParser(
        prog="b1500_step_stress",
        description="B1500 Step Stress Measurement with Thorlabs Power Meter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
────────
  # List available VISA resources
  python -m b1500_step_stress --list-resources

  # Run step stress test with defaults
  python -m b1500_step_stress --b1500 "GPIB0::17::INSTR" --pm "USB0::0x1313::0x8078::P1234567::INSTR"

  # Custom measurement and stress parameters
  python -m b1500_step_stress \\
    --b1500 "GPIB0::17::INSTR" \\
    --pm "USB0::0x1313::0x8078::P1234567::INSTR" \\
    --meas-start 0 --meas-stop 3 --meas-steps 31 \\
    --stress-start 2 --stress-stop 6 --stress-step 0.5 --stress-duration 120

  # Disable power meter, run IV sweep only
  python -m b1500_step_stress \\
    --b1500 "GPIB0::17::INSTR" \\
    --no-power-meter \\
    --output-folder /data/vcsel_test \\
    --device-name VCSEL_L12
        """,
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )
    
    parser.add_argument(
        "--list-resources",
        action="store_true",
        help="List all VISA resources and exit",
    )
    
    # Device connection
    parser.add_argument(
        "--b1500",
        type=str,
        help="VISA resource string for Keysight B1500 (e.g., GPIB0::17::INSTR)",
    )
    
    parser.add_argument(
        "--pm",
        type=str,
        help="VISA resource string for Thorlabs power meter",
    )
    
    # Measurement settings
    parser.add_argument(
        "--smu",
        type=int,
        default=1,
        help="SMU channel number (default: 1)",
    )
    
    parser.add_argument(
        "--meas-mode",
        choices=["iv", "vi"],
        default="iv",
        help="Measurement mode: IV (source V, measure I) or VI (default: iv)",
    )
    
    parser.add_argument(
        "--meas-start",
        type=float,
        default=0.0,
        help="Measurement start value (V or A) (default: 0.0)",
    )
    
    parser.add_argument(
        "--meas-stop",
        type=float,
        default=2.0,
        help="Measurement stop value (default: 2.0)",
    )
    
    parser.add_argument(
        "--meas-steps",
        type=int,
        default=21,
        help="Number of measurement points (default: 21)",
    )
    
    parser.add_argument(
        "--meas-dwell",
        type=float,
        default=0.1,
        help="Dwell time (seconds) (default: 0.1)",
    )
    
    parser.add_argument(
        "--meas-compliance",
        type=float,
        default=0.1,
        help="Measurement compliance limit (A or V) (default: 0.1)",
    )
    
    # Stress settings
    parser.add_argument(
        "--stress-mode",
        choices=["voltage", "current"],
        default="voltage",
        help="Stress mode (default: voltage)",
    )
    
    parser.add_argument(
        "--stress-start",
        type=float,
        default=2.0,
        help="Starting stress level (V or A) (default: 2.0)",
    )
    
    parser.add_argument(
        "--stress-stop",
        type=float,
        default=5.0,
        help="Final stress level (default: 5.0)",
    )
    
    parser.add_argument(
        "--stress-step",
        type=float,
        default=0.5,
        help="Stress level step size (default: 0.5)",
    )
    
    parser.add_argument(
        "--stress-duration",
        type=float,
        default=60.0,
        help="Stress duration per level (seconds) (default: 60)",
    )
    
    parser.add_argument(
        "--stress-interval",
        type=float,
        default=1.0,
        help="Stress monitoring sample interval (seconds) (default: 1.0)",
    )
    
    parser.add_argument(
        "--stress-compliance",
        type=float,
        default=0.1,
        help="Stress compliance limit (default: 0.1)",
    )
    
    # Power meter
    parser.add_argument(
        "--no-power-meter",
        action="store_true",
        help="Disable power meter readout",
    )
    
    parser.add_argument(
        "--wavelength",
        type=float,
        default=850.0,
        help="Power meter wavelength (nm) (default: 850)",
    )
    
    # Output
    parser.add_argument(
        "--output-folder",
        type=str,
        default="results",
        help="Output folder for results (default: results)",
    )
    
    parser.add_argument(
        "--device-name",
        type=str,
        default="Device_001",
        help="Device identifier for output files (default: Device_001)",
    )
    
    parser.add_argument(
        "--no-autosave",
        action="store_true",
        help="Disable automatic data saving",
    )
    
    parser.add_argument(
        "--no-initial-meas",
        action="store_true",
        help="Skip initial measurement (baseline)",
    )
    
    return parser


def main():
    """Run CLI"""
    parser = build_parser()
    args = parser.parse_args()
    
    # List resources and exit
    if args.list_resources:
        b1500 = B1500Controller()
        print("\n=== Available VISA Resources ===\n")
        
        all_res = b1500.list_all_resources()
        if not all_res:
            print("No VISA resources found. Install pyvisa with: pip install pyvisa pyvisa-py")
            return 1
        
        gpib_res = [r for r in all_res if "GPIB" in r.upper()]
        usb_res = [r for r in all_res if "USB" in r.upper()]
        
        if gpib_res:
            print("GPIB Devices (B1500):")
            for r in gpib_res:
                print(f"  {r}")
        
        if usb_res:
            print("\nUSB Devices (Power Meter):")
            for r in usb_res:
                print(f"  {r}")
        
        if not gpib_res and not usb_res:
            print("No GPIB or USB devices found.")
            print(f"Total resources: {len(all_res)}")
            for r in all_res:
                print(f"  {r}")
        
        return 0
    
    # Check required arguments
    if not args.b1500 and not args.pm:
        parser.print_help()
        print("\nError: At least one of --b1500 or --pm is required")
        return 1
    
    # Connect to devices
    b1500 = B1500Controller()
    power_meter = ThorlabsPowerMeterController()
    
    print("\n=== Connecting Devices ===\n")
    
    if args.b1500:
        success, msg = b1500.connect(args.b1500)
        print(f"B1500: {msg}")
        if not success:
            return 1
    
    if args.pm and not args.no_power_meter:
        success, msg = power_meter.connect(args.pm)
        print(f"Power Meter: {msg}")
        if not success:
            return 1
    
    # Build configuration
    config = StepStressConfig(
        measurement=MeasurementSettings(
            smu=args.smu,
            mode=args.meas_mode,
            start=args.meas_start,
            stop=args.meas_stop,
            steps=args.meas_steps,
            dwell_s=args.meas_dwell,
            compliance=args.meas_compliance,
        ),
        stress=StressSettings(
            mode=args.stress_mode,
            start_value=args.stress_start,
            stop_value=args.stress_stop,
            step_value=args.stress_step,
            duration_s=args.stress_duration,
            sample_interval_s=args.stress_interval,
            compliance=args.stress_compliance,
        ),
        initial_measurement=not args.no_initial_meas,
        enable_power_meter=not args.no_power_meter,
        power_wavelength_nm=args.wavelength,
        output_folder=args.output_folder,
        device_name=args.device_name,
        autosave=not args.no_autosave,
    )
    
    # Run test
    print("\n=== Starting Test ===\n")
    
    engine = StepStressMeasurementEngine(b1500, power_meter, config)
    engine.on_log = print
    
    meas_data, stress_data = engine.run()
    
    # Cleanup
    print("\n=== Cleanup ===\n")
    
    if b1500.connected:
        b1500.disconnect()
        print("B1500 disconnected")
    
    if power_meter.connected:
        power_meter.disconnect()
        print("Power meter disconnected")
    
    print(f"\nCollected {len(meas_data)} measurement points, {len(stress_data)} stress points")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
