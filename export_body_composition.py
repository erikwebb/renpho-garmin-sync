#!/usr/bin/env python3
"""Export full Garmin Connect body composition history to Google Sheets / Excel / CSV.

Fetches the complete historical record of weigh-ins and body composition metrics
from Garmin Connect, processes them into human-readable imperial (lbs) and
metric (kg) units, and outputs:
1. A formatted Microsoft Excel (.xlsx) workbook ready for Google Sheets
2. A standard comma-separated (.csv) file
3. Direct synchronization to Google Drive desktop sync folder (if present)
4. Copies TSV data to macOS clipboard (pbcopy) for instant 1-click paste into sheets.new

Usage:
    python3 export_body_composition.py
    ./export.sh --open-sheet
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from datetime import date, datetime, timezone
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

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


KG_TO_LBS = 2.20462262185
MS_PER_YEAR = 31557600000.0  # 365.25 days in milliseconds
DEFAULT_GARMIN_TOKENS = Path.home() / ".garminconnect"


def find_google_drive_dir() -> Path | None:
    """Detect local Google Drive for Desktop CloudStorage folder if present."""
    cloud_storage = Path.home() / "Library" / "CloudStorage"
    if not cloud_storage.is_dir():
        return None

    candidates = list(cloud_storage.glob("GoogleDrive-*/My Drive"))
    if candidates:
        for c in candidates:
            if "gmail.com" in c.parent.name:
                return c
        return candidates[0]

    classic = Path.home() / "Google Drive" / "My Drive"
    if classic.is_dir():
        return classic

    return None


def copy_to_clipboard(tsv_text: str) -> bool:
    """Copy text to macOS clipboard using pbcopy."""
    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(tsv_text.encode("utf-8"))
        return proc.returncode == 0
    except Exception:
        return False


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



def fetch_garmin_history(
    garmin: Garmin,
    start_date: str = "2000-01-01",
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all weigh-ins and body composition entries between start_date and end_date."""
    if end_date is None:
        end_date = date.today().isoformat()

    print(f"Fetching body composition history from Garmin Connect ({start_date} to {end_date})...")
    res = garmin.get_weigh_ins(start_date, end_date)
    summaries = res.get("dailyWeightSummaries", []) if isinstance(res, dict) else []

    all_metrics: list[dict[str, Any]] = []
    for s in summaries:
        metrics = s.get("allWeightMetrics", [])
        if metrics:
            all_metrics.extend(metrics)
        elif s.get("latestWeight"):
            all_metrics.append(s["latestWeight"])

    print(f"Retrieved {len(all_metrics)} total weigh-in measurements across {len(summaries)} active days.")
    return all_metrics


def transform_measurement(m: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw Garmin measurement dictionary into clean export fields."""
    cal_date = m.get("calendarDate") or ""
    ts_gmt = m.get("timestampGMT")
    ts_local = m.get("date")

    time_str = ""
    if ts_local:
        try:
            dt_local = datetime.fromtimestamp(ts_local / 1000.0)
            time_str = dt_local.strftime("%H:%M:%S")
        except Exception:
            pass

    iso_gmt = ""
    if ts_gmt:
        try:
            iso_gmt = datetime.fromtimestamp(ts_gmt / 1000.0, tz=timezone.utc).isoformat()
        except Exception:
            pass

    weight_g = m.get("weight")
    weight_kg = round(weight_g / 1000.0, 2) if weight_g is not None else None
    weight_lbs = round((weight_g / 1000.0) * KG_TO_LBS, 2) if weight_g is not None else None

    bmi = round(m["bmi"], 1) if m.get("bmi") is not None else None
    body_fat = round(m["bodyFat"], 1) if m.get("bodyFat") is not None else None

    fat_mass_lbs = (
        round(weight_lbs * (body_fat / 100.0), 2)
        if weight_lbs is not None and body_fat is not None
        else None
    )
    fat_mass_kg = (
        round(weight_kg * (body_fat / 100.0), 2)
        if weight_kg is not None and body_fat is not None
        else None
    )

    muscle_g = m.get("muscleMass")
    muscle_kg = round(muscle_g / 1000.0, 2) if muscle_g is not None else None
    muscle_lbs = (
        round((muscle_g / 1000.0) * KG_TO_LBS, 2) if muscle_g is not None else None
    )
    muscle_pct = (
        round((muscle_g / weight_g) * 100.0, 1) if muscle_g and weight_g else None
    )

    bone_g = m.get("boneMass")
    bone_kg = round(bone_g / 1000.0, 2) if bone_g is not None else None
    bone_lbs = round((bone_g / 1000.0) * KG_TO_LBS, 2) if bone_g is not None else None

    body_water = round(m["bodyWater"], 1) if m.get("bodyWater") is not None else None
    water_mass_lbs = (
        round(weight_lbs * (body_water / 100.0), 2)
        if weight_lbs is not None and body_water is not None
        else None
    )
    water_mass_kg = (
        round(weight_kg * (body_water / 100.0), 2)
        if weight_kg is not None and body_water is not None
        else None
    )

    visceral_fat = m.get("visceralFat")
    meta_age_ms = m.get("metabolicAge")
    meta_age_years = round(meta_age_ms / MS_PER_YEAR, 1) if meta_age_ms else None

    delta_g = m.get("weightDelta")
    delta_lbs = round((delta_g / 1000.0) * KG_TO_LBS, 2) if delta_g is not None else None
    delta_kg = round(delta_g / 1000.0, 2) if delta_g is not None else None

    source = m.get("sourceType") or "UNKNOWN"
    sample_pk = m.get("samplePk") or ""

    return {
        "Date": cal_date,
        "Time": time_str,
        "Weight (lbs)": weight_lbs,
        "Weight (kg)": weight_kg,
        "BMI": bmi,
        "Body Fat (%)": body_fat,
        "Fat Mass (lbs)": fat_mass_lbs,
        "Fat Mass (kg)": fat_mass_kg,
        "Muscle Mass (lbs)": muscle_lbs,
        "Muscle Mass (kg)": muscle_kg,
        "Muscle Mass (%)": muscle_pct,
        "Bone Mass (lbs)": bone_lbs,
        "Bone Mass (kg)": bone_kg,
        "Body Water (%)": body_water,
        "Water Mass (lbs)": water_mass_lbs,
        "Water Mass (kg)": water_mass_kg,
        "Visceral Fat": visceral_fat,
        "Metabolic Age (yr)": meta_age_years,
        "Weight Delta (lbs)": delta_lbs,
        "Weight Delta (kg)": delta_kg,
        "Source": source,
        "Timestamp UTC": iso_gmt,
        "Entry ID": sample_pk,
    }


def write_csv(rows: list[dict[str, Any]], filepath: Path) -> None:
    """Write rows to a CSV file."""
    if not rows:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with filepath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in r.items()})


def generate_tsv(rows: list[dict[str, Any]]) -> str:
    """Generate tab-delimited string of rows for clipboard pasting."""
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()), delimiter="\t")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return out.getvalue()


def write_xlsx(rows: list[dict[str, Any]], filepath: Path) -> None:
    """Write rows to a beautifully styled Excel workbook optimized for Google Sheets import."""
    if not OPENPYXL_AVAILABLE or not rows:
        return

    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Body Composition History"

    headers = list(rows[0].keys())
    ws.append(headers)

    # Styles
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    zebra_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")
    thin_border_side = Side(style="thin", color="E0E0E0")
    thin_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
    ws.row_dimensions[1].height = 28

    for row_idx, r in enumerate(rows, start=2):
        row_values = [r[h] for h in headers]
        ws.append(row_values)
        ws.row_dimensions[row_idx].height = 20

        is_even = row_idx % 2 == 0
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            if is_even:
                cell.fill = zebra_fill

            if header in ("Date", "Time", "Source"):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif "ID" in header or "Timestamp" in header:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")

            if "Delta" in header:
                cell.number_format = "+0.00;-0.00;0.00"
            elif "%" in header or "BMI" in header or "Age" in header:
                cell.number_format = "0.0"
            elif "(lbs)" in header or "(kg)" in header:
                cell.number_format = "0.00"
            elif "Visceral" in header:
                cell.number_format = "0"

    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(filepath)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Garmin Connect body composition history to Google Sheets / Excel / CSV."
    )
    parser.add_argument(
        "--start-date",
        default="2000-01-01",
        help="Earliest date to export in YYYY-MM-DD format (default: 2000-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Latest date to export in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--sort",
        choices=["desc", "asc"],
        default="desc",
        help="Sort order by date (default: desc, most recent first)",
    )
    parser.add_argument(
        "--tokens",
        default=os.environ.get("GARMINTOKENS", str(DEFAULT_GARMIN_TOKENS)),
        help="Path to Garmin Connect token storage directory (default: ~/.garminconnect)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent / "data"),
        help="Local directory to write backup export files (default: ./data)",
    )
    parser.add_argument(
        "--skip-local",
        "--no-local",
        dest="skip_local",
        action="store_true",
        help="Skip writing export files to the local output directory",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Do not copy TSV data to macOS clipboard",
    )
    parser.add_argument(
        "--open-sheet",
        action="store_true",
        help="Automatically open https://sheets.new in default browser",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send a macOS desktop notification upon completion or failure",
    )
    args = parser.parse_args()

    try:
        # 1. Login to Garmin Connect
        tokens_path = Path(args.tokens).expanduser()
        print(f"1. Authenticating with Garmin Connect using tokens at {tokens_path}...")
        try:
            garmin = Garmin()
            garmin.login(str(tokens_path))
            print(f"   Logged in successfully as {garmin.get_full_name()}.")
        except Exception as exc:
            print(f"ERROR: Failed to authenticate with Garmin Connect: {exc}", file=sys.stderr)
            if args.notify:
                send_notification("Garmin Export Failed", f"Garmin auth failed: {exc}")
            return 1

        # 2. Fetch full history
        print(f"2. Fetching weigh-in metrics from {args.start_date} to {args.end_date}...")
        raw_measurements = fetch_garmin_history(garmin, args.start_date, args.end_date)
        if not raw_measurements:
            print("No measurements found.")
            if args.notify:
                send_notification("Garmin Export", "No weigh-in measurements found.")
            return 0

        # 3. Sort & transform
        print("3. Transforming measurements and calculating derived metrics...")
        sort_reverse = args.sort == "desc"
        raw_measurements.sort(
            key=lambda m: m.get("timestampGMT") or m.get("date") or 0,
            reverse=sort_reverse,
        )

        rows = [transform_measurement(m) for m in raw_measurements]
        print(f"   Prepared {len(rows)} fully formatted records.")

        # 4. Write local outputs
        if not args.skip_local:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            csv_path = out_dir / "Garmin_Body_Composition_History.csv"
            write_csv(rows, csv_path)
            print(f"4. Saved local CSV: {csv_path}")

            xlsx_path = out_dir / "Garmin_Body_Composition_History.xlsx"
            if OPENPYXL_AVAILABLE:
                write_xlsx(rows, xlsx_path)
                print(f"   Saved local Excel: {xlsx_path}")
        else:
            print("4. Skipped saving local files (--skip-local).")

        # 5. Write to Google Drive desktop folder if present
        gdrive_dir = find_google_drive_dir()
        if gdrive_dir and gdrive_dir.is_dir():
            gdrive_csv = gdrive_dir / "Garmin_Body_Composition_History.csv"
            write_csv(rows, gdrive_csv)
            print(f"5. Synced to Google Drive: {gdrive_csv}")

            if OPENPYXL_AVAILABLE:
                gdrive_xlsx = gdrive_dir / "Garmin_Body_Composition_History.xlsx"
                write_xlsx(rows, gdrive_xlsx)
                print(f"   Synced to Google Drive: {gdrive_xlsx}")
        else:
            print("5. Google Drive desktop folder not found (skipped direct folder sync).")

        # 6. Copy TSV to clipboard for instant pasting
        tsv_content = generate_tsv(rows)
        if not args.no_clipboard:
            if copy_to_clipboard(tsv_content):
                print("6. Copied entire dataset to macOS clipboard as tab-separated values!")
                print("   👉 You can open any Google Sheet (or https://sheets.new) and press Cmd+V to paste.")
            else:
                print("6. Clipboard copy skipped or failed.")

        # 7. Optional browser launch
        if args.open_sheet:
            print("7. Opening https://sheets.new in your default web browser...")
            subprocess.run(["open", "https://sheets.new"])

        print("\nExport completed successfully!")
        if args.notify:
            if gdrive_dir and not args.skip_local:
                dest = "Google Drive & local data/"
            elif gdrive_dir:
                dest = "Google Drive"
            elif not args.skip_local:
                dest = "local data/"
            else:
                dest = "clipboard"
            send_notification(
                "Garmin Body Composition",
                f"Exported {len(rows)} records ({dest}).",
            )
        return 0

    except Exception as exc:
        print(f"ERROR: Export failed: {exc}", file=sys.stderr)
        if getattr(args, "notify", False):
            send_notification("Garmin Export Failed", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
