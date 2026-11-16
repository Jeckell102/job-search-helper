"""Compatibility entry point for the packaged scrape-to-FIRST-PASS workflow."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from job_search_helper.scrape_first_pass import *

if __name__ == '__main__':
    raise SystemExit(main())
