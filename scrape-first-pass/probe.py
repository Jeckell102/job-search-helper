"""Compatibility entry point for the packaged read-only workflow inspector."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
if __name__ == '__main__':
    runpy.run_module('job_search_helper.pipeline_probe', run_name='__main__')
