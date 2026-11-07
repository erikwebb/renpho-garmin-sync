# Upstream Patches & API Reverse Engineering Notes

This document contains reverse-engineering findings, bug reports, and reference patches suitable for upstream contribution to [`ChocoTonic/renpho-py`](https://github.com/ChocoTonic/renpho-py) and related Renpho / Garmin integration libraries.

---

## 1. Renpho Cloud Login Failure: `code=-114` ("Decryption failed")

### Target
`renpho.client.RenphoClient` (in `renpho-py` / `renpho-api`)

### Problem
Starting late 2026, calls to Renpho's `/renpho-data/user/login` endpoint fail with:
```json
{"code": -114, "msg": "Decryption failed"}
```
even when credentials and payload encryption are 100% valid.

### Root Cause
Renpho's cloud gateway now rejects login requests if client platform metadata headers are missing on the initial unauthenticated request. Previous versions of the library only attached these headers or tokens *after* successful authentication.

### Fix / Pull Request
Initialize the requests `Session` with client metadata and an Android OkHttp User-Agent before calling `login()`:

```python
class PatchedRenphoClient(RenphoClient):
    def __init__(self, email: str, password: str, *, debug: bool = False):
        super().__init__(email, password, debug=debug)
        self._session.headers.update(
            {
                "appVersion": APP_VERSION,  # e.g. "3.8.0"
                "platform": PLATFORM,      # e.g. "android"
                "User-Agent": "okhttp/4.9.3",
            }
        )

    def _post(self, endpoint: str, body: dict, *, auth: bool = True, extra_headers: dict | None = None) -> dict:
        result = super()._post(endpoint, body, auth=auth, extra_headers=extra_headers)
        # Renpho's newer gateway responses use `message` instead of `msg`
        if "msg" not in result and "message" in result:
            result["msg"] = result["message"]
        return result
```

---

## 2. Table Sharding Fallback for Wi-Fi Scales (`user_id % 24`)

### Target
`RenphoClient.get_measurements()` / `get_all_measurements()`

### Problem
For Wi-Fi scale models (such as the Renpho Elis Nova) that connect directly to home 2.4 GHz Wi-Fi without the mobile app, `client.get_device_info()` often returns an empty `scale: []` array or omits `tableName`. As a result, standard library calls fail to locate the user's measurement table.

### Root Cause & Findings
Renpho shards user measurements across 24 database tables:
`measurements_info_0` through `measurements_info_23`.

The shard index is deterministically calculated using modulo arithmetic on the user's 64-bit integer `user_id`:
$$\text{shard\_index} = \text{user\_id} \pmod{24}$$

### Fix / Pull Request
When `device_info` does not supply an active table name, dynamically compute the shard:

```python
if target_user_id is not None:
    shard_table = f"measurements_info_{int(target_user_id) % 24}"
```

---

## 3. Dual-Endpoint Measurement Querying

### Target
Measurement retrieval across firmware revisions.

### Problem
Calling only `queryAllMeasureDataList` misses newer body composition records, while querying only `queryBodyCompositionMeasureData` misses older records or entries uploaded via alternate scale models.

### Fix
Query both endpoints across pagination and deduplicate using unique measurement IDs:

```python
for endpoint_key in ("body_composition_measurements", "measurements"):
    endpoint = ENDPOINTS[endpoint_key]
    # paginate page 1..N and deduplicate on record id / timestamp
```

---

## 4. Renpho Timestamp Offset & Timezone Corruption

### Target
Data transformation / normalization in Renpho client wrappers.

### Problem
The integer Unix `timeStamp` / `time_stamp` field in Renpho JSON payloads is frequently misaligned by +8 hours (server backend time) relative to when the weigh-in actually occurred.

### Fix
Always prioritize `localCreatedAt` formatted string along with the `timeZone` field (e.g. `"-4:00"`):

```python
local_created = record.get("localCreatedAt")
tz_str = record.get("timeZone")
if local_created:
    dt = datetime.strptime(str(local_created), "%Y-%m-%d %H:%M:%S")
    if tz_str:
        parts = str(tz_str).strip().split(":")
        hours = int(parts[0])
        mins = int(parts[1]) if len(parts) > 1 else 0
        if hours < 0:
            mins = -mins
        dt = dt.replace(tzinfo=timezone(timedelta(hours=hours, minutes=mins)))
    return int(dt.timestamp())
```

---

## 5. Garmin FIT `muscle_mass` (Percentage vs. Kilograms)

### Target
`python-garminconnect` body composition wrappers and sync scripts.

### Problem
Renpho's `muscle` metric is returned as a **percentage (%) of total weight** (e.g., `51.2` for 51.2%).
Garmin Connect's underlying FIT scale message (`WeightScaleMesg`) strictly expects **`muscle_mass` in kilograms (kg)**.

If a script forwards `muscle` directly to `garmin.add_body_composition()`, a 90 kg user with 50% muscle will see 50 kg recorded, leading to corrupted trends in Garmin Connect.

### Fix
```python
raw_muscle = positive_float(record.get("muscle"))
if raw_muscle is not None:
    # If raw_muscle is a percentage (e.g., 51.2% and fat is 20%)
    if percent_fat is not None and (raw_muscle + percent_fat) <= 105.0 and raw_muscle > 20.0:
        muscle_mass_kg = round(weight_kg * (raw_muscle / 100.0), 2)
    else:
        muscle_mass_kg = round(raw_muscle, 2)
```
