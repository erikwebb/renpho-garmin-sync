# Renpho to Garmin Sync

## Architecture & API Notes

- **Wi-Fi Sync**: Supported Wi-Fi smart scales push measurements directly to `cloud.renpho.com` without needing the mobile app open at weigh-in time.
- **Database Routing**: Renpho shards measurements across 24 tables (`measurements_info_0` through `measurements_info_23`) dynamically computed via `user_id % 24`.
- **Timestamp Handling**: Always parse `localCreatedAt` alongside `timeZone` (e.g. `-4:00`). Renpho's raw `timeStamp` integer field is offset by 8 hours and must not be used as the primary timestamp.

## Upstream Tracking

- When doing any work, check for updates to [`docs/UPSTREAM_NOTES.md`](docs/UPSTREAM_NOTES.md) to keep upstream PRs, issues, and library compatibility in sync.



