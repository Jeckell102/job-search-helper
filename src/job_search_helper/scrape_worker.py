"""Internal scan worker. Public start commands use the full workflow in runner."""
from .runner import scrape_main

if __name__ == '__main__':
    raise SystemExit(scrape_main())
