#!/usr/bin/env bash
set -euo pipefail

observer_dir=/run/jsh-s5-amphenol-release-06
observer_src=/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/site-source/ancillary_process_witness.py
observer_sha=f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819

[ ! -e "$observer_dir" ] && [ ! -L "$observer_dir" ] || {
    printf '%s\n' 'The observer directory already exists. Leave it intact and report this message.'
    exit 1
}
printf '%s  %s\n' "$observer_sha" "$observer_src" | sha256sum --check --status
sudo /usr/bin/install -d -m 0755 -o root -g root -- "$observer_dir"
sudo /usr/bin/install -m 0555 -o root -g root -- "$observer_src" "$observer_dir/observer.py"
printf '%s  %s\n' "$observer_sha" "$observer_dir/observer.py" | sha256sum --check --status
exec sudo /usr/bin/python3 -I -B "$observer_dir/observer.py" \
    --socket "$observer_dir/observer.sock" --launch-uid 1000 \
    --maintenance-id s5-amphenol-qualified-release-20261121-06 --seconds 900 --listener-port 18789 \
    --pid 1249 --pid 4467 \
    --route /home/chris/job-search-helper_old \
    --route /home/chris/job-search-helper_old_copy \
    --route '/home/chris/job-search-helper backup' \
    --route /home/chris/job-search-helper-sqlite-migration-20261012 \
    --route /home/chris/.exchange-park-s4-atomic-01-copy \
    --route /home/chris/.exchange-park-s4-atomic-01-backup \
    --route /home/chris/.exchange-park-s4-atomic-01-migration
