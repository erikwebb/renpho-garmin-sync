# Renpho to Garmin Sync

## Architecture & API Notes

- **Wi-Fi Sync**: Supported Wi-Fi smart scales push measurements directly to `cloud.renpho.com` without needing the mobile app open at weigh-in time.
- **Database Routing**: Renpho shards measurements across 24 tables (`measurements_info_0` through `measurements_info_23`) dynamically computed via `user_id % 24`.
- **Timestamp Handling**: Always parse `localCreatedAt` alongside `timeZone` (e.g. `-4:00`). Renpho's raw `timeStamp` integer field is offset by 8 hours and must not be used as the primary timestamp.

## Scheduled Jobs (macOS LaunchAgents)

- **Daily Scale Sync** (`com.erikwebb.renpho-garmin-sync`):
  - Script: `scripts/run_sync.sh` (`sync_renpho_to_garmin.py --notify`)
  - Schedule: Daily at 9:00 AM
  - Log: `logs/sync.log`
- **Weekly Body Composition Export** (`com.erikwebb.renpho-garmin-export`):
  - Script: `scripts/run_export.sh` (`export_body_composition.py --skip-local --no-clipboard --notify`)
  - Schedule: Weekly on Sundays at 9:30 AM
  - Log: `logs/export.log`

## Manual Execution Scripts

- `./scripts/export.sh`: Runs [export_body_composition.py](file:///Users/erikwebb/Development/renpho-garmin-sync/export_body_composition.py) interactively with the project virtual environment, forwarding any CLI options (e.g. `--open-sheet`).

## Upstream Tracking

- When doing any work, check for updates to [`docs/UPSTREAM_NOTES.md`](docs/UPSTREAM_NOTES.md) to keep upstream PRs, issues, and library compatibility in sync.



