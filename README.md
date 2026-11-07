# Renpho to Garmin Connect Sync

[![CI](https://github.com/erikwebb/renpho-garmin-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/erikwebb/renpho-garmin-sync/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Automated, direct synchronization of smart scale body composition metrics from **Renpho Health Cloud** (`cloud.renpho.com`) to **Garmin Connect** without requiring Garmin's expensive Index S2 scale.

---

## Highlights

* **Direct Wi-Fi Cloud Sync**: Works seamlessly with Wi-Fi smart scales (such as the **Renpho Elis Nova**). Weigh in, step off, and the scale automatically uploads over Wi-Fi directly to the cloud—no mobile app or Bluetooth pairing needed at weigh-in time.
* **Full Body Composition via FIT**: Generates proper Garmin FIT scale messages including:
  * Weight (kg / lbs)
  * Body Fat (%)
  * Skeletal Muscle Mass (converted to kg)
  * Hydration / Body Water (%)
  * Bone Mass (kg)
  * BMI & Basal Metabolic Rate (BMR)
  * Visceral Fat Rating & Metabolic Age
* **Unit Conversion & Sanitation**: Renpho reports muscle as a percentage (%) of body weight, whereas Garmin's FIT message format requires muscle in kilograms (kg). The sync engine handles conversions and heuristics automatically.
* **Smart Non-Destructive Deduplication**: Inspects existing Garmin entries. If an existing entry is weight-only (e.g., synced from Apple Health or MyFitnessPal), the script *upgrades* it with full body composition data instead of creating duplicates.
* **Session Persistence & Concurrency**: Supports target user IDs (`--target-user-id`) so you can authenticate using a secondary profile while syncing measurements for a primary profile, preventing the Renpho mobile app from getting logged out.
* **Automated History Export**: Includes a full export utility that formats complete historical weigh-ins into styled Excel (`.xlsx`), CSV, Google Drive sync folders, or instant clipboard copy (`pbcopy`) for `sheets.new`.

---

## Reverse Engineering & Fixes

This project includes solutions for several undocumented Renpho API quirks:
1. **Oct 2026 Login Header Requirement**: Renpho's API gateway rejects login requests with `code=-114 ("Decryption failed")` unless client metadata headers (`appVersion`, `platform`, `okhttp` User-Agent) are supplied on the initial unauthenticated request.
2. **24-Shard Database Routing**: Renpho shards measurements across `measurements_info_0` through `measurements_info_23` calculated via `user_id % 24`. The sync script computes this dynamically when device metadata is omitted.
3. **Timezone & Epoch Correction**: Renpho's raw `timeStamp` field is notoriously misaligned by server backend offsets. We parse `localCreatedAt` alongside `timeZone` offsets for accurate local timestamps.

*(See [UPSTREAM_NOTES.md](UPSTREAM_NOTES.md) for detailed technical reports and patches for upstream client libraries).*

---

## Requirements

* Python 3.10+
* A Renpho Health account and compatible smart scale (Wi-Fi or Bluetooth)
* A Garmin Connect account

---

## Quickstart

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/erikwebb/renpho-garmin-sync.git
cd renpho-garmin-sync

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your Renpho credentials:

```dotenv
RENPHO_EMAIL=your_email@example.com
RENPHO_PASSWORD=your_password_here

# Optional: Target user ID if using a secondary account
# RENPHO_TARGET_USER_ID=1234567890123456789

# Optional: Custom path for Garmin tokens (defaults to ~/.garminconnect)
# GARMINTOKENS=~/.garminconnect
```

### 3. Initialize Garmin Connect Authentication

Run the sync script in dry-run mode. If Garmin tokens do not exist in `~/.garminconnect`, you will be prompted for your Garmin Connect credentials once to create and store OAuth tokens locally:

```bash
./sync_renpho_to_garmin.py --dry-run
```

---

## Usage

### Synchronize Weigh-Ins

```bash
# Preview measurements that would be uploaded without changing Garmin Connect
./sync_renpho_to_garmin.py --dry-run

# Run full sync
./sync_renpho_to_garmin.py

# Sync only measurements from the last 7 days
./sync_renpho_to_garmin.py --since 2026-11-01

# Limit batch upload to the last N measurements
./sync_renpho_to_garmin.py --limit 5

# Force re-uploading entries even if already in local state
./sync_renpho_to_garmin.py --force
```

### Export Historical Body Composition

```bash
# Export Garmin history to CSV and styled Excel in data/
./export.sh

# Open Google Sheet in browser ready for 1-click paste (copies TSV to macOS clipboard)
./export.sh --open-sheet
```

---

## CLI Reference

### `sync_renpho_to_garmin.py`

| Flag | Description |
|---|---|
| `--dry-run` | Fetch and display measurements without uploading to Garmin |
| `--since YYYY-MM-DD` | Filter to only sync measurements on or after date |
| `--limit N` | Maximum number of records to upload in a single run |
| `--force` | Bypass local and remote deduplication checks |
| `--notify` | Trigger macOS desktop notification upon completion or failure |
| `--debug` | Enable verbose HTTP debug output for Renpho API |
| `--target-user-id ID` | Override target Renpho profile user ID |

---

## Automated Scheduling (macOS `launchd`)

Templates for running automatic background syncs on macOS via `launchd` are provided in [`templates/`](templates/).

### Daily Scale Sync (9:00 AM)

```bash
cp templates/com.example.renpho-garmin-sync.plist ~/Library/LaunchAgents/com.user.renpho-garmin-sync.plist

# Update paths inside the plist to point to your repository clone
sed -i '' "s|/PATH/TO/renpho-garmin-sync|$(pwd)|g" ~/Library/LaunchAgents/com.user.renpho-garmin-sync.plist

# Load the agent
launchctl load ~/Library/LaunchAgents/com.user.renpho-garmin-sync.plist
```

### Weekly History Export (Sundays 9:30 AM)

```bash
cp templates/com.example.renpho-garmin-export.plist ~/Library/LaunchAgents/com.user.renpho-garmin-export.plist
sed -i '' "s|/PATH/TO/renpho-garmin-sync|$(pwd)|g" ~/Library/LaunchAgents/com.user.renpho-garmin-export.plist
launchctl load ~/Library/LaunchAgents/com.user.renpho-garmin-export.plist
```

The runner scripts (`run_sync.sh` and `run_export.sh`) include a built-in network readiness guard that polls for active Wi-Fi and DNS resolution for up to 30 seconds after waking from system sleep before firing requests.

---

## License

This project is licensed under the [MIT License](LICENSE).
