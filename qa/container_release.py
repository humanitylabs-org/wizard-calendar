#!/usr/bin/env python3
"""Compatibility entry point for the native-architecture release runner.
Set ARCH=arm64 or amd64 and DOCKER_CMD as needed. No dual-architecture emulation.
Outputs live in the staged checkout; see tools/alpha_runner.py and RELEASE.md.
"""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/alpha_runner.py'), run_name='__main__')
