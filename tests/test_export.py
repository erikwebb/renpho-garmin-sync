"""Unit tests for Garmin body composition history transformations and exports."""

from pathlib import Path
from export_body_composition import generate_tsv, transform_measurement, write_csv, write_xlsx


def test_transform_measurement_normalizes_fields():
    raw_garmin = {
        "calendarDate": "2026-11-06",
        "date": 1794060000000,
        "timestampGMT": 1794060000000,
        "weight": 80000,  # 80 kg in grams
        "bmi": 24.5,
        "bodyFat": 18.5,
        "muscleMass": 40000,  # 40 kg in grams
        "boneMass": 3500,  # 3.5 kg in grams
        "bodyWater": 60.0,
        "visceralFat": 6,
        "metabolicAge": 946728000000,  # ~30 years in ms
        "weightDelta": -500,
        "sourceType": "INDEX_SCALE",
        "samplePk": "sample_12345",
    }

    transformed = transform_measurement(raw_garmin)

    assert transformed["Date"] == "2026-11-06"
    assert transformed["Weight (kg)"] == 80.0
    # 80 kg * 2.20462262185 ~= 176.37 lbs
    assert abs(transformed["Weight (lbs)"] - 176.37) < 0.05
    assert transformed["BMI"] == 24.5
    assert transformed["Body Fat (%)"] == 18.5
    assert transformed["Fat Mass (kg)"] == round(80.0 * 0.185, 2)
    assert transformed["Muscle Mass (kg)"] == 40.0
    assert transformed["Muscle Mass (%)"] == 50.0
    assert transformed["Bone Mass (kg)"] == 3.5
    assert transformed["Body Water (%)"] == 60.0
    assert transformed["Visceral Fat"] == 6
    assert abs(transformed["Metabolic Age (yr)"] - 30.0) < 0.1
    assert transformed["Source"] == "INDEX_SCALE"
    assert transformed["Entry ID"] == "sample_12345"


def test_generate_tsv_formats_columns():
    rows = [
        {"Date": "2026-11-06", "Weight (kg)": 80.0, "Body Fat (%)": 18.5},
        {"Date": "2026-11-05", "Weight (kg)": 80.5, "Body Fat (%)": 18.6},
    ]
    tsv = generate_tsv(rows)
    lines = tsv.strip().split("\r\n" if "\r\n" in tsv else "\n")

    assert len(lines) == 3
    assert lines[0] == "Date\tWeight (kg)\tBody Fat (%)"
    assert lines[1] == "2026-11-06\t80.0\t18.5"
    assert lines[2] == "2026-11-05\t80.5\t18.6"


def test_write_csv(tmp_path: Path):
    rows = [{"Date": "2026-11-06", "Weight (kg)": 80.0}]
    csv_file = tmp_path / "test_output.csv"
    write_csv(rows, csv_file)

    assert csv_file.is_file()
    content = csv_file.read_text(encoding="utf-8")
    assert "Date,Weight (kg)" in content
    assert "2026-11-06,80.0" in content


def test_write_xlsx(tmp_path: Path):
    rows = [
        {
            "Date": "2026-11-06",
            "Time": "09:00:00",
            "Weight (lbs)": 176.37,
            "Weight (kg)": 80.0,
            "BMI": 24.5,
            "Body Fat (%)": 18.5,
            "Fat Mass (lbs)": 32.63,
            "Fat Mass (kg)": 14.8,
            "Muscle Mass (lbs)": 88.18,
            "Muscle Mass (kg)": 40.0,
            "Muscle Mass (%)": 50.0,
            "Bone Mass (lbs)": 7.72,
            "Bone Mass (kg)": 3.5,
            "Body Water (%)": 60.0,
            "Water Mass (lbs)": 105.82,
            "Water Mass (kg)": 48.0,
            "Visceral Fat": 6,
            "Metabolic Age (yr)": 30.0,
            "Weight Delta (lbs)": -1.1,
            "Weight Delta (kg)": -0.5,
            "Source": "SCALE",
            "Timestamp UTC": "2026-11-06T14:00:00+00:00",
            "Entry ID": "12345",
        }
    ]
    xlsx_file = tmp_path / "test_output.xlsx"
    write_xlsx(rows, xlsx_file)

    assert xlsx_file.is_file()
    assert xlsx_file.stat().st_size > 0
