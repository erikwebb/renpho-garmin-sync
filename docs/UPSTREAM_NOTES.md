# Upstream Patches, Issues & PR Tracker

This document tracks reverse-engineering findings, upstream pull requests, issues, and community discussions across the Renpho and Garmin open-source ecosystems.

---

## Upstream Status & PR Matrix

| Issue / Feature | Target Project | Status | Upstream Links |
|---|---|---|---|
| **Login `-114` Decryption Failure** | `renpho-py` / `renpho-api` | Merged in `renpho-py` v1.3.0; Open in `renpho-api` | [ChocoTonic/renpho-py#5](https://github.com/ChocoTonic/renpho-py/pull/5)<br>[danvaneijck/renpho-api#12](https://github.com/danvaneijck/renpho-api/issues/12)<br>[danvaneijck/renpho-api#13](https://github.com/danvaneijck/renpho-api/pull/13) |
| **Timestamp & Timezone Mismatch (+8h Skew)** | `renpho-py` | **PR Submitted (Open)** | [ChocoTonic/renpho-py#11](https://github.com/ChocoTonic/renpho-py/pull/11) |
| **24-Shard Database Routing (`user_id % 24`)** | `renpho-py` | Merged in `renpho-py` v1.3.0 | [ChocoTonic/renpho-py#8](https://github.com/ChocoTonic/renpho-py/pull/8) |
| **Request Timeouts & Bounded Pagination** | `renpho-py` | Merged in `renpho-py` v1.3.0 | [ChocoTonic/renpho-py#7](https://github.com/ChocoTonic/renpho-py/pull/7) |
| **Fork Reconciliation & PyPI Handoff** | `renpho-api` | **Discussion Opened** | [danvaneijck/renpho-api#15](https://github.com/danvaneijck/renpho-api/issues/15) |
| **Garmin FIT Muscle Mass (% vs. kg)** | `renpho-garmin-sync` | Implemented locally | [sync_renpho_to_garmin.py](https://github.com/erikwebb/renpho-garmin-sync/blob/main/sync_renpho_to_garmin.py) |

---

## 1. Renpho Cloud Login Failure: `code=-114` ("Decryption failed")

* **Upstream PR (Merged)**: [`ChocoTonic/renpho-py#5: Fix Renpho login decryption failure and verify request headers`](https://github.com/ChocoTonic/renpho-py/pull/5)
* **Upstream Issue**: [`ChocoTonic/renpho-py#1: Login fails with code -114`](https://github.com/ChocoTonic/renpho-py/issues/1)
* **Legacy Upstream Issue**: [`danvaneijck/renpho-api#12: Login Failed - code=-114`](https://github.com/danvaneijck/renpho-api/issues/12)
* **Legacy Upstream PR**: [`danvaneijck/renpho-api#13: fix(client): send appVersion on login so gateway can decrypt`](https://github.com/danvaneijck/renpho-api/pull/13)

### Problem & Resolution
Starting in October 2026, Renpho's API gateway (`cloud.renpho.com`) rejects `/renpho-data/user/login` requests with `code=-114 ("Decryption failed")` if client metadata headers are omitted on the initial unauthenticated call.

The gateway uses the `appVersion` header to select the appropriate decryption key. Without it, the server falls back to an incompatible key. The fix attaches `appVersion`, `platform`, and the Android `okhttp/4.9.3` User-Agent to the session before calling `login()`. This is available in `renpho-py>=1.3.0`.

---

## 2. Timestamp Offset & Timezone Corruption (+8h Server Skew)

* **Upstream PR**: [`ChocoTonic/renpho-py#11: feat(models): parse localCreatedAt with timeZone and normalize timestamps`](https://github.com/ChocoTonic/renpho-py/pull/11)
* **Local Implementation**: [`sync_renpho_to_garmin.py: extract_epoch_seconds()`](https://github.com/erikwebb/renpho-garmin-sync/blob/main/sync_renpho_to_garmin.py#L241-L281)

### Problem & Resolution
Renpho's raw `timeStamp` integer field in measurement payloads is frequently misaligned by +8 hours (server backend time relative to UTC) or local time without timezone context. 

PR [#11](https://github.com/ChocoTonic/renpho-py/pull/11) adds `parse_timestamp()` and enhances `Measurement.from_dict()` in `renpho-py` to prioritize `localCreatedAt` alongside `timeZone` (e.g. `"-04:00"` or `"-4:00"`, correctly propagating sign into minute calculations) before falling back to `timeStamp` or `createdAt`.

---

## 3. 24-Shard Database Routing for Wi-Fi Scales (`user_id % 24`)

* **Upstream PR (Merged)**: [`ChocoTonic/renpho-py#8: Add validated account login and strict measurement profile collection`](https://github.com/ChocoTonic/renpho-py/pull/8)
* **Legacy PR**: [`danvaneijck/renpho-api#9: Tape-measure support and multi-account fetch`](https://github.com/danvaneijck/renpho-api/pull/9)

### Problem & Resolution
For Wi-Fi scales (such as the Renpho Elis Nova) that connect directly to home 2.4 GHz Wi-Fi without the mobile app open, `get_device_info()` often omits the scale's `tableName`.

Renpho shards measurements across 24 database tables (`measurements_info_0` through `measurements_info_23`). The shard index is deterministically derived via:
$$\text{shard\_index} = \text{user\_id} \pmod{24}$$
Both `renpho-py>=1.3.0` and our sync engine dynamically route queries to `measurements_info_{user_id % 24}` when device discovery returns an empty table name.

---

## 4. Fork Reconciliation & Community Transition

* **Discussion Issue**: [`danvaneijck/renpho-api#15: Proposal: Reconcile with maintained community continuation (renpho-py / @ChocoTonic)`](https://github.com/danvaneijck/renpho-api/issues/15)

### Problem & Resolution
The original `renpho-api` package has been dormant since August 2026, causing new users to hit the `-114` decryption crash without realizing `ChocoTonic/renpho-py` exists as a maintained drop-in replacement. Issue [#15](https://github.com/danvaneijck/renpho-api/issues/15) proposes adding a maintainer pointer or deprecation notice on PyPI/GitHub.

---

## 5. Garmin FIT Muscle Mass (% vs. kg)

* **Local Implementation**: [`sync_renpho_to_garmin.py: map_renpho_to_garmin()`](https://github.com/erikwebb/renpho-garmin-sync/blob/main/sync_renpho_to_garmin.py#L317-L327)
* **Unit Tests**: [`tests/test_sync.py: test_map_renpho_to_garmin_muscle_percentage_to_kg_conversion()`](https://github.com/erikwebb/renpho-garmin-sync/blob/main/tests/test_sync.py#L65-L93)

### Problem & Resolution
Renpho returns `muscle` as a percentage (%) of body weight, but Garmin's FIT message format (`WeightScaleMesg`) strictly expects `muscle_mass` in kilograms (kg). 

The conversion engine calculates:
$$\text{muscle\_mass\_kg} = \text{round}\left(\text{weight\_kg} \times \frac{\text{muscle\_percent}}{100.0}, 2\right)$$
with safety heuristics (`(raw_muscle + percent_fat) <= 105.0`) to avoid double-converting if an alternate scale model reports in kilograms.
