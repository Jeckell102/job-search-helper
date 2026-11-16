"""Compatibility test discovery for the packaged workflow's single test suite."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
from test_scrape_first_pass import *
