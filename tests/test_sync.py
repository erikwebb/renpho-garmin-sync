"""Unit tests for timestamp parsing, timezone offset handling, and metric conversion."""

from datetime import datetime, timedelta, timezone

from sync_renpho_to_garmin import extract_epoch_seconds, map_renpho_to_garmin, positive_float


def test_extract_epoch_seconds_resolves_server_offset_mismatch():
    """Verify that Renpho's skewed +8 hour server timeStamp is ignored in favor of localCreatedAt + timeZone."""
    # User weighs in at 10:00:00 AM EDT (UTC-4)
    # Expected UTC: 14:00:00 UTC
    expected_utc = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
    true_epoch = int(expected_utc.timestamp())

    # Raw Renpho timeStamp skewed by +8 hours (server backend time)
    skewed_server_timestamp = true_epoch + (8 * 3600)

    record = {
        "id": 555,
        "timeStamp": skewed_server_timestamp,
        "localCreatedAt": "2026-11-06 10:00:00",
        "timeZone": "-04:00",
        "weight": 80.0,
    }

    resolved_epoch = extract_epoch_seconds(record)

    assert resolved_epoch == true_epoch
    assert resolved_epoch != skewed_server_timestamp
    assert skewed_server_timestamp - resolved_epoch == 8 * 3600


def test_extract_epoch_seconds_handles_single_digit_and_half_hour_timezones():
    # Single digit negative timezone: "-4:00"
    rec_single = {
        "localCreatedAt": "2026-11-06 10:00:00",
        "timeZone": "-4:00",
    }
    exp_single = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert extract_epoch_seconds(rec_single) == int(exp_single.timestamp())

    # Half hour timezone: "-03:30" (e.g. Newfoundland)
    rec_nl = {
        "localCreatedAt": "2026-11-06 10:00:00",
        "timeZone": "-03:30",
    }
    exp_nl = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone(timedelta(hours=-3, minutes=-30)))
    assert extract_epoch_seconds(rec_nl) == int(exp_nl.timestamp())

    # Positive timezone: "+05:30" (e.g. India)
    rec_pos = {
        "localCreatedAt": "2026-11-06 10:00:00",
        "timeZone": "+05:30",
    }
    exp_pos = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert extract_epoch_seconds(rec_pos) == int(exp_pos.timestamp())


def test_extract_epoch_seconds_fallbacks():
    # 13-digit millisecond timestamp fallback
    rec_ms = {"timeStamp": 1700000000000}
    assert extract_epoch_seconds(rec_ms) == 1700000000

    # 10-digit epoch timestamp fallback
    rec_sec = {"timeStamp": 1700000000}
    assert extract_epoch_seconds(rec_sec) == 1700000000

    # UTC createdAt fallback
    rec_created = {"createdAt": "2026-11-06 10:00:00"}
    exp_created = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone.utc)
    assert extract_epoch_seconds(rec_created) == int(exp_created.timestamp())

    # Empty dictionary returns 0
    assert extract_epoch_seconds({}) == 0


def test_map_renpho_to_garmin_muscle_percentage_to_kg_conversion():
    """Verify that Renpho muscle percentage (%) is converted into kilograms (kg) for Garmin FIT."""
    record = {
        "localCreatedAt": "2026-11-06 09:00:00",
        "timeZone": "-04:00",
        "weight": 100.0,
        "bodyfat": 20.0,
        "muscle": 50.0,  # 50.0% of 100kg = 50.0kg
        "water": 55.0,
        "bone": 4.0,
        "bmi": 26.0,
        "bmr": 1850.0,
        "visfat": 7.0,
        "bodyage": 32.0,
        "bodyShape": 2.0,
    }

    mapped = map_renpho_to_garmin(record)
    assert mapped is not None
    assert mapped["weight"] == 100.0
    assert mapped["percent_fat"] == 20.0
    # 50% of 100 kg is 50.0 kg
    assert mapped["muscle_mass"] == 50.0
    assert mapped["percent_hydration"] == 55.0
    assert mapped["bone_mass"] == 4.0
    assert mapped["bmi"] == 26.0
    assert mapped["basal_met"] == 1850.0
    assert mapped["visceral_fat_rating"] == 7
    assert mapped["metabolic_age"] == 32


def test_map_renpho_to_garmin_rejects_missing_or_zero_weight():
    assert map_renpho_to_garmin({}) is None
    assert map_renpho_to_garmin({"weight": 0}) is None
    assert map_renpho_to_garmin({"weight": -5.0}) is None


def test_positive_float_helper():
    assert positive_float("75.5") == 75.5
    assert positive_float(0) is None
    assert positive_float(-10) is None
    assert positive_float(None) is None
    assert positive_float("invalid") is None
