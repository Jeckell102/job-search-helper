# Install v3.3

1. Stop the currently running helper with Ctrl+C.
2. Extract this archive into a temporary directory.
3. Run the included installer against your existing project.

```bash
cd ~
rm -rf /tmp/job-search-v33
mkdir -p /tmp/job-search-v33

tar -xzf ~/Downloads/job-search-helper-v3.3-pro-work.tar.gz -C /tmp/job-search-v33

cd /tmp/job-search-v33
chmod +x install-v3.3.sh
./install-v3.3.sh /home/chris/job-search-helper
```

The installer preserves `.env`, `.state`, `.secrets`, `credentials.json`, and `.venv`, and runs the one-time Google Sheet migration/backfill.

After installation:

```bash
cd ~/job-search-helper
./job-search-scraper start
```

Then open ChatGPT Work and use `prompts/WORK-JOB-REVIEWER.txt` with the connected Google Sheet.
