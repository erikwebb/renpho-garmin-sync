#!/usr/bin/env python3
"""
Sync body composition measurements from Renpho Health (cloud.renpho.com) to Garmin Connect.

Features:
- Connects directly to the Renpho Health Cloud API (includes the Oct 2026 login header fix).
- Queries both `queryBodyCompositionMeasureData` and `queryAllMeasureDataList` for complete history.
- Reuses existing Garmin Connect OAuth tokens in `~/.garminconnect`.
- Deduplicates against both local state (`~/.garminconnect/renpho_synced_ids.json`) and existing
  Garmin Connect body-composition entries (preserving/upgrading weight-only entries that lack body fat %).
- Supports `--dry-run`, `--since YYYY-MM-DD`, and `--limit N`.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure garminconnect is importable (installed package or local development checkout)
try:
    from garminconnect import Garmin
except ImportError:
    for candidate in (
        Path(__file__).resolve().parent.parent / "python-garminconnect",
        Path.home() / "Development" / "python-garminconnect",
    ):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break
    from garminconnect import Garmin
from renpho.client import RenphoAPIError, RenphoClient  # noqa: E402
from renpho.constants import APP_VERSION, ENDPOINTS, PLATFORM, SUCCESS_CODES  # noqa: E402
from renpho.crypto import decrypt_response, encrypt_request  # noqa: E402

DEFAULT_GARMIN_TOKENS = Path.home() / ".garminconnect"
DEFAULT_STATE_FILE = Path.home() / ".garminconnect" / "renpho_synced_ids.json"
DEFAULT_SESSION_FILE = Path.home() / ".garminconnect" / "renpho_session.json"
DEFAULT_ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_dotenv(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file if present."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def send_notification(title: str, message: str, subtitle: str = "") -> None:
    """Send a macOS desktop notification via osascript."""
    if sys.platform != "darwin":
        return
    try:
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
        safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
        safe_sub = subtitle.replace("\\", "\\\\").replace('"', '\\"')
        sub_clause = f'subtitle "{safe_sub}" ' if safe_sub else ""
        script = f'display notification "{safe_msg}" with title "{safe_title}" {sub_clause}sound name "default"'
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        print(f"Warning: Failed to deliver desktop notification: {exc}", file=sys.stderr)


class PatchedRenphoClient(RenphoClient):
    """RenphoClient with session token caching and dual-endpoint history fetch."""

    def __init__(self, email: str, password: str, *, debug: bool = False):
        super().__init__(email, password, debug=debug)
        # Ensure User-Agent is set across either renpho-py or legacy renpho-api
        session = getattr(self, "_session", None)
        if session is None and hasattr(self, "_transport"):
            session = getattr(self._transport, "session", None)
        if session is not None:
            session.headers.update(
                {
                    "appVersion": APP_VERSION,
                    "platform": PLATFORM,
                    "User-Agent": "okhttp/4.9.3",
                }
            )

    def _post(
        self,
        endpoint: str,
        body: dict,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict:
        result = super()._post(endpoint, body, auth=auth, **kwargs)
        # Normalize Renpho's newer `message` field into `msg` so callers surface it
        if isinstance(result, dict) and "msg" not in result and "message" in result:
            result["msg"] = result["message"]
        return result

    def load_session(self, session_file: Path) -> bool:
        """Load cached token and user_id if present for this email."""
        if not session_file.is_file():
            return False
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            if data.get("email") == self.email and data.get("token") and data.get("user_id"):
                self.token = str(data["token"])
                self.user_id = data["user_id"]
                return True
        except Exception:
            pass
        return False

    def save_session(self, session_file: Path) -> None:
        """Persist token and user_id to avoid unnecessary login() calls."""
        if not self.token or not self.user_id:
            return
        session_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "email": self.email,
            "token": self.token,
            "user_id": self.user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        session_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        session_file.chmod(0o600)

    def ensure_authenticated(self, session_file: Path) -> bool:
        """Reuse cached token if accepted by server, otherwise login() and save."""
        if self.load_session(session_file):
            try:
                self.get_device_info()
                return False  # Reused cached session
            except Exception:
                self.token = None
                self.user_id = None
        self.login()
        self.save_session(session_file)
        return True  # Performed fresh login

    def fetch_complete_history(
        self, page_size: int = 100, target_user_id: str | int | None = None
    ) -> list[dict[str, Any]]:
        """Fetch all scale measurements across both body-composition and legacy endpoints."""
        if not self.token:
            self.login()

        targets: list[tuple[str, str]] = []
        if target_user_id is not None:
            shard_table = f"measurements_info_{int(target_user_id) % 24}"
            targets.append((shard_table, str(target_user_id)))
        else:
            device_info = self.get_device_info()
            scales = device_info.get("scale", []) if isinstance(device_info, dict) else []

            # Build list of (table_name, user_id) pairs to query
            for s in scales:
                table_name = s.get("tableName")
                if not table_name:
                    continue
                user_ids = [str(u) for u in (s.get("userIds") or [])]
                uid = (
                    user_ids[0]
                    if user_ids and str(self.user_id) not in user_ids
                    else str(self.user_id)
                )
                targets.append((table_name, uid))

            # Fallback to deterministic shard table if device/count returned no scales
            if self.user_id is not None:
                try:
                    shard_table = f"measurements_info_{int(self.user_id) % 24}"
                    if not any(t == shard_table for t, _ in targets):
                        targets.append((shard_table, str(self.user_id)))
                except (ValueError, TypeError):
                    pass

        seen_keys: set[str] = set()
        all_records: list[dict[str, Any]] = []

        for table_name, uid in targets:
            for endpoint_key in ("body_composition_measurements", "measurements"):
                endpoint = ENDPOINTS[endpoint_key]
                page = 1
                prev_sig = None
                while page <= 500:
                    query = {
                        "pageNum": page,
                        "pageSize": page_size,
                        "userIds": [str(uid)],
                        "tableName": table_name,
                    }
                    try:
                        res = self._post(endpoint, encrypt_request(query))
                        code = res.get("code")
                        msg = (res.get("msg") or res.get("message") or "").lower()
                        if msg != "success" and code not in SUCCESS_CODES:
                            break
                        if not res.get("data"):
                            break
                        page_data = decrypt_response(res["data"])
                    except Exception as exc:
                        if self.debug:
                            print(f"  [debug] {endpoint_key} p.{page} on {table_name}: {exc}")
                        break

                    records = self._extract_records(page_data)
                    if not records:
                        break

                    sig = json.dumps(records, sort_keys=True, default=str)
                    if sig == prev_sig:
                        break
                    prev_sig = sig

                    for r in records:
                        rec_id = r.get("id")
                        ts = r.get("timeStamp") or r.get("time_stamp")
                        dedup_key = f"id:{rec_id}" if rec_id is not None else f"ts:{ts}"
                        if dedup_key not in seen_keys:
                            seen_keys.add(dedup_key)
                            all_records.append(r)

                    if len(records) < page_size:
                        break
                    page += 1

        # Sort oldest -> newest so historical backfill runs chronologically
        all_records.sort(key=extract_epoch_seconds)
        return all_records


def extract_epoch_seconds(record: dict[str, Any]) -> int:
    """Extract Unix timestamp in seconds from a Renpho measurement record.

    Prioritizes `localCreatedAt` + `timeZone` because Renpho's raw `timeStamp` field
    is often misaligned or timezone-shifted by their cloud backend.
    """
    local_created = record.get("localCreatedAt")
    tz_str = record.get("timeZone")
    if local_created:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(str(local_created), fmt)
                if tz_str:
                    parts = str(tz_str).strip().split(":")
                    hours = int(parts[0])
                    mins = int(parts[1]) if len(parts) > 1 else 0
                    if hours < 0:
                        mins = -mins
                    dt = dt.replace(tzinfo=timezone(timedelta(hours=hours, minutes=mins)))
                else:
                    dt = dt.astimezone()
                return int(dt.timestamp())
            except (ValueError, IndexError):
                pass

    ts = record.get("timeStamp") or record.get("time_stamp")
    if ts is not None:
        ts_int = int(float(ts))
        if ts_int > 10**12:
            ts_int //= 1000
        return ts_int

    created_at = record.get("createdAt")
    if created_at:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(str(created_at), fmt).replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                pass
    return 0


def positive_float(val: Any) -> float | None:
    """Return float(val) if > 0 else None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def map_renpho_to_garmin(record: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw Renpho measurement dict into kwargs for Garmin.add_body_composition()."""
    weight_kg = positive_float(record.get("weight"))
    if not weight_kg:
        return None

    epoch_sec = extract_epoch_seconds(record)
    if epoch_sec <= 0:
        return None

    dt_local = datetime.fromtimestamp(epoch_sec).astimezone()
    timestamp_iso = dt_local.isoformat()

    percent_fat = positive_float(record.get("bodyfat"))
    percent_hydration = positive_float(record.get("water"))
    bone_mass = positive_float(record.get("bone"))
    bmi = positive_float(record.get("bmi"))
    basal_met = positive_float(record.get("bmr"))
    visceral_fat_rating = positive_float(record.get("visfat"))
    metabolic_age = positive_float(record.get("bodyage"))
    physique_rating = positive_float(record.get("bodyShape"))

    # Renpho stores `muscle` as a percentage (%) of total weight, while Garmin's FIT
    # WeightScaleMesg expects `muscle_mass` in kilograms (kg).
    raw_muscle = positive_float(record.get("muscle"))
    muscle_mass_kg: float | None = None
    if raw_muscle is not None:
        if percent_fat is not None and (raw_muscle + percent_fat) <= 105.0 and raw_muscle > 20.0:
            muscle_mass_kg = round(weight_kg * (raw_muscle / 100.0), 2)
        else:
            # Fallback in case a specific scale model reports muscle directly in kg
            muscle_mass_kg = round(raw_muscle, 2)

    return {
        "timestamp": timestamp_iso,
        "weight": round(weight_kg, 2),
        "percent_fat": round(percent_fat, 2) if percent_fat is not None else None,
        "percent_hydration": round(percent_hydration, 2) if percent_hydration is not None else None,
        "bone_mass": round(bone_mass, 2) if bone_mass is not None else None,
        "muscle_mass": muscle_mass_kg,
        "basal_met": round(basal_met, 1) if basal_met is not None else None,
        "metabolic_age": int(round(metabolic_age)) if metabolic_age is not None else None,
        "visceral_fat_rating": int(round(visceral_fat_rating)) if visceral_fat_rating is not None else None,
        "physique_rating": int(round(physique_rating)) if physique_rating is not None else None,
        "bmi": round(bmi, 2) if bmi is not None else None,
    }


def load_synced_state(state_file: Path) -> set[str]:
    if not state_file.is_file():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return set(str(x) for x in data.get("synced_keys", []))
    except Exception:
        return set()


def save_synced_state(state_file: Path, synced_keys: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "synced_keys": sorted(synced_keys),
    }
    state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    load_dotenv(DEFAULT_ENV_FILE)

    parser = argparse.ArgumentParser(
        description="Sync body composition measurements from Renpho Health to Garmin Connect."
    )
    parser.add_argument(
        "--renpho-email",
        default=os.environ.get("RENPHO_EMAIL"),
        help="Renpho Health account email (or set RENPHO_EMAIL in .env)",
    )
    parser.add_argument(
        "--renpho-password",
        default=os.environ.get("RENPHO_PASSWORD"),
        help="Renpho Health account password (or set RENPHO_PASSWORD in .env)",
    )
    parser.add_argument(
        "--target-user-id",
        default=os.environ.get("RENPHO_TARGET_USER_ID"),
        help="Optional Renpho userId to read measurements for (allows logging in with a secondary account so the main phone app stays logged in)",
    )
    parser.add_argument(
        "--garmin-tokens",
        default=os.environ.get("GARMINTOKENS", str(DEFAULT_GARMIN_TOKENS)),
        help="Path to Garmin Connect token directory (default: ~/.garminconnect)",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="Path to local JSON state file tracking synced Renpho measurements",
    )
    parser.add_argument(
        "--session-file",
        default=str(DEFAULT_SESSION_FILE),
        help="Path to cached Renpho session token file",
    )
    parser.add_argument(
        "--since",
        help="Only sync measurements on or after YYYY-MM-DD",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of measurements to upload in this run (most recent N if combined with --latest)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even if already present in local state or Garmin Connect",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and preview measurements that would be uploaded without modifying Garmin Connect",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging for Renpho API calls",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send a macOS desktop notification upon completion or failure",
    )
    args = parser.parse_args()

    renpho_email = args.renpho_email
    if not renpho_email:
        renpho_email = input("Renpho Health Email: ").strip()
    renpho_password = args.renpho_password
    if not renpho_password:
        renpho_password = getpass.getpass("Renpho Health Password: ")

    since_epoch = 0
    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        since_epoch = int(since_dt.timestamp())

    try:
        print(f"1. Authenticating with Renpho Health ({renpho_email})...")
        renpho = PatchedRenphoClient(renpho_email, renpho_password, debug=args.debug)
        session_file = Path(args.session_file).expanduser()
        try:
            fresh_login = renpho.ensure_authenticated(session_file)
        except RenphoAPIError as exc:
            print(f"ERROR: Renpho login failed: {exc}", file=sys.stderr)
            if args.notify:
                send_notification("Renpho → Garmin Sync Failed", f"Renpho login failed: {exc}")
            return 1

        auth_mode = "fresh login" if fresh_login else "reused cached token"
        target_uid = args.target_user_id
        print(
            f"   Authenticated ({auth_mode}, user_id={renpho.user_id}"
            + (f", target_user_id={target_uid}" if target_uid else "")
            + "). Fetching measurements..."
        )
        raw_measurements = renpho.fetch_complete_history(target_user_id=target_uid)
        print(f"   Found {len(raw_measurements)} total Renpho scale measurements.")

        if not raw_measurements:
            if args.notify:
                send_notification("Renpho → Garmin Sync", "No measurements found in Renpho account.")
            return 0

        print(f"2. Authenticating with Garmin Connect using tokens at {args.garmin_tokens}...")
        garmin = Garmin()
        garmin.login(args.garmin_tokens)
        print(f"   Logged in to Garmin Connect as {garmin.get_full_name()}.")

        # Fetch existing Garmin body composition entries across the full date range
        earliest_epoch = extract_epoch_seconds(raw_measurements[0])
        start_date_str = (
            datetime.fromtimestamp(earliest_epoch).strftime("%Y-%m-%d")
            if earliest_epoch > 0
            else "2018-01-01"
        )
        end_date_str = datetime.now().strftime("%Y-%m-%d")
        print(f"3. Checking existing Garmin Connect weigh-ins ({start_date_str} .. {end_date_str})...")
        existing_garmin = garmin.get_body_composition(start_date_str, end_date_str)
        garmin_entries = existing_garmin.get("dateWeightList", []) if isinstance(existing_garmin, dict) else []

        # Collect timestamps (in seconds) and dates of Garmin entries that ALREADY have bodyFat populated
        garmin_full_epochs: list[int] = []
        garmin_full_dates: set[str] = set()
        for entry in garmin_entries:
            if entry.get("bodyFat") is not None:
                ts_gmt = entry.get("timestampGMT") or entry.get("date")
                if ts_gmt:
                    garmin_full_epochs.append(int(ts_gmt) // 1000)
                cal_date = entry.get("calendarDate")
                if cal_date:
                    garmin_full_dates.add(cal_date)

        print(
            f"   Garmin has {len(garmin_entries)} total weight entries "
            f"({len(garmin_full_epochs)} with body composition, "
            f"{len(garmin_entries) - len(garmin_full_epochs)} weight-only)."
        )

        state_file = Path(args.state_file).expanduser()
        synced_keys = load_synced_state(state_file)

        to_upload: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        skipped_already_synced = 0
        skipped_in_garmin = 0

        for rec in raw_measurements:
            epoch_sec = extract_epoch_seconds(rec)
            if epoch_sec < since_epoch:
                continue

            mapped = map_renpho_to_garmin(rec)
            if not mapped:
                continue

            rec_id = rec.get("id")
            state_key = f"id:{rec_id}" if rec_id is not None else f"ts:{epoch_sec}"

            if not args.force:
                if state_key in synced_keys:
                    skipped_already_synced += 1
                    continue

                # Check if Garmin already has a full body-composition entry within +/- 10 minutes
                if any(abs(epoch_sec - g_ts) <= 600 for g_ts in garmin_full_epochs):
                    skipped_in_garmin += 1
                    synced_keys.add(state_key)
                    continue

            to_upload.append((state_key, rec, mapped))

        if args.limit and len(to_upload) > args.limit:
            to_upload = to_upload[-args.limit :]

        print(
            f"4. Sync plan: {len(to_upload)} measurement(s) to upload "
            f"(skipped {skipped_already_synced} in local state, "
            f"{skipped_in_garmin} already in Garmin with body composition)."
        )

        if not to_upload:
            save_synced_state(state_file, synced_keys)
            print("Everything is up to date!")
            if args.notify:
                send_notification("Renpho → Garmin Sync", "Everything is up to date (no new weigh-ins).")
            return 0

        print("\nMeasurements queued for Garmin Connect:")
        print(
            f"{'Date/Time':<22} {'Weight (kg / lbs)':<20} {'Fat %':<7} {'Water %':<8} "
            f"{'Muscle (kg)':<12} {'Bone (kg)':<10} {'BMI':<6} {'BMR':<6} {'VisFat':<6} {'Age':<4}"
        )
        print("-" * 110)
        for _, _, m in to_upload[-25:]:
            w_kg = m["weight"]
            w_lbs = w_kg * 2.20462262
            dt_disp = m["timestamp"][:19].replace("T", " ")
            print(
                f"{dt_disp:<22} {w_kg:>6.2f}kg ({w_lbs:>6.2f}lb) "
                f"{str(m['percent_fat'] or '-'):<7} {str(m['percent_hydration'] or '-'):<8} "
                f"{str(m['muscle_mass'] or '-'):<12} {str(m['bone_mass'] or '-'):<10} "
                f"{str(m['bmi'] or '-'):<6} {str(m['basal_met'] or '-'):<6} "
                f"{str(m['visceral_fat_rating'] or '-'):<6} {str(m['metabolic_age'] or '-'):<4}"
            )
        if len(to_upload) > 25:
            print(f"... and {len(to_upload) - 25} earlier measurement(s).")

        if args.dry_run:
            print("\n[Dry Run] No measurements were uploaded to Garmin Connect.")
            if args.notify:
                send_notification("Renpho → Garmin Sync", f"[Dry Run] {len(to_upload)} measurement(s) queued.")
            return 0

        print(f"\n5. Uploading {len(to_upload)} FIT body-composition file(s) to Garmin Connect...")
        uploaded_count = 0
        for idx, (state_key, _, m) in enumerate(to_upload, start=1):
            dt_disp = m["timestamp"][:19].replace("T", " ")
            try:
                garmin.add_body_composition(**m)
                synced_keys.add(state_key)
                save_synced_state(state_file, synced_keys)
                uploaded_count += 1
                print(f"   [{idx}/{len(to_upload)}] Uploaded {dt_disp} ({m['weight']} kg)")
                if idx < len(to_upload):
                    time.sleep(1.2)
            except Exception as exc:
                print(f"   [{idx}/{len(to_upload)}] FAILED {dt_disp}: {exc}", file=sys.stderr)

        print(f"\nDone! Successfully uploaded {uploaded_count}/{len(to_upload)} measurement(s) to Garmin Connect.")
        if args.notify:
            noun = "weigh-in" if uploaded_count == 1 else "weigh-ins"
            if uploaded_count == len(to_upload):
                msg = f"Synced {uploaded_count} new {noun} to Garmin Connect."
            else:
                msg = f"Synced {uploaded_count}/{len(to_upload)} {noun} (some failed)."
            send_notification("Renpho → Garmin Sync", msg)
        return 0

    except Exception as exc:
        print(f"ERROR: Sync process encountered an unhandled exception: {exc}", file=sys.stderr)
        if getattr(args, "notify", False):
            send_notification("Renpho → Garmin Sync Failed", f"{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
