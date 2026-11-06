# Aircraft Deceleration Calibration — SITL Test Runbook

Version 1.0 \| 6 November 2026 \| Phase 4 regression

Purpose: repeat a calibration or recalibration of an aircraft profile, verify conservative convergence and persistence, and independently inspect governed-speed recovery in ClickHouse. This document separates demonstrated steps from configuration details that still require confirmation.

# 1. Scope and prerequisites

- A valid Flight Execution Record (FER) configured for calibration (flight_calibration enabled), linked to the intended aircraft and an eligible Route segment.

- Aircraft and calibration profile exist; verified profiles may be recalibrated. The calibration Route must permit uninterrupted AUTO flight and must not terminate the selected segment at a managed intersection.

- NAVProxy, ArduPilot SITL, DroneNav API, RabbitMQ telemetry, and ClickHouse are available. Ensure sufficient Route distance for five repeated slowdowns and recoveries.

- Flight Band commanded_cruise_speed_ft_s is configured. For the demonstrated test it was 14.67 ft/s; calibration target was 7.335 ft/s.

Operational safety gates observed in implementation: AUTO flight mode, active Route, no active failsafe, route/lane/altitude conformance, clear intersection controls, and sufficient distance. Calibration readiness requires 15 consecutive stable speed samples within ±1 ft/s of governed cruise speed.

# 2. Start and configure the test environment

## 2.1 SITL and flight configuration

Start ArduPilot SITL with the rotor configuration matching the aircraft profile, at the intended departure DronePort. Confirm mission origin and vehicle configuration before launch. The exact SITL invocation and port arguments were not preserved in the test record; insert the tested command here before treating this as a fully unattended procedure.

> \# SITE-SPECIFIC: ArduPilot SITL startup command (to be recorded)  
> \# SITE-SPECIFIC: NAVProxy flight-launch command (to be recorded)

## 2.2 Start ClickHouse telemetry collector

From the DroneNav API project root, in a separate terminal:

> set -a  
> source .env  
> set +a  
> python3 -m app.navproxy.telemetry.collector

The collector consumes RabbitMQ queue dronenav.telemetry.clickhouse and writes to ClickHouse table dronenav.telemetry_raw. Confirm the collector remains running during the flight.

## 2.3 Submit calibration request

The request payload uses message_type calibration.request with route_id, route_segment_index and target_speed_ft_s. The precise transport/invocation command was not captured in this session; use the existing calibration tooling and record the verified invocation here. Do not send a second request while one is pending.

> message_type: calibration.request  
> route_id: 01a1916b-0cd9-7357-83a2-aa8e28ccb1b3  
> route_segment_index: 1  
> target_speed_ft_s: 7.335

The route ID and segment above are examples from the 6 November test, not universal defaults. The target is half of that test’s 14.67 ft/s governed speed; do not assume a 50% target for other configurations without checking the tooling.

# 3. Monitor NAVProxy calibration

Log file used in the regression: ~/logs/navproxy.log. Review recent calibration lines without opening the entire log:

> grep -iE 'calibration\|deceleration\|convergence' ~/logs/navproxy.log \| tail -100

For the final five per-attempt values:

> grep 'Calibration measured deceleration:' ~/logs/navproxy.log \| tail -5

Expected sequence: readiness reaches 15 stable samples; calibration activates; speed drops toward target; a deceleration measurement is recorded; governed cruise speed is restored; the cycle repeats until convergence or failure.

## 3.1 Convergence policy verified in source

Source: app/navproxy/tooling/calibrate_deceleration.py, get_converged_deceleration() (approximately lines 676–698 at test time).

- Require at least five valid measurements; evaluate the most recent five.

- Compute the average and reject invalid, non-finite, or non-positive measurements.

- Every one of the five must lie within ±10% of their average.

- On convergence, return min(recent_measurements), deliberately choosing the conservative deceleration value.

In execution_service.py the resulting value is sent to patch_calibration_profile() with calibration_success=True, planned_deceleration_ft_s2, calibration_flight_execution_id, sample_count, and updated_by="dronenav".

# 4. Verify the aircraft profile in Drupal

After NAVProxy reports “Aircraft calibration profile updated,” inspect the corresponding aircraft calibration profile. Confirm:

- planned_deceleration_ft_s2 equals the conservative minimum of the converged measurements.

- deceleration_verified = true and operational_status = active.

- sample_count and calibration flight association, where displayed, match the test.

A successful recalibration of an already verified profile updates its existing value; it is not restricted to first-time calibration. For unsuccessful calibration, the intended policy is to retain the previous planned value while marking verification false and status inactive; this failure path was not tested in the November 6 regression.

# 5. Analyze ClickHouse telemetry

Use the FER UUID of the run. The following query was executed successfully from the API project root with .env loaded:

> python3 - \<\<'PY'  
> from app.navproxy.telemetry.collector import connect_clickhouse  
> client = connect_clickhouse()  
> try:  
> result = client.query("""  
> SELECT count() AS samples,  
> min(observed_at) AS first_sample,  
> max(observed_at) AS last_sample,  
> min(ground_speed_ft_s) AS min_speed,  
> max(ground_speed_ft_s) AS max_speed,  
> round(avg(ground_speed_ft_s), 3) AS avg_speed  
> FROM telemetry_raw  
> WHERE flight_execution_id =  
> '01a1b2be-2b38-7b5d-96da-69f7ca301621'  
> """)  
> for row in result.result_rows:  
> print(row)  
> finally:  
> client.close()  
> PY

To examine recovery around an event, change the time range as appropriate:

> SELECT toStartOfSecond(observed_at) AS second,  
> round(avg(ground_speed_ft_s), 3) AS speed_ft_s  
> FROM telemetry_raw  
> WHERE flight_execution_id = '01a1b2be-2b38-7b5d-96da-69f7ca301621'  
> AND observed_at \>= '2026-11-06 21:25:35'  
> AND observed_at \<= '2026-11-06 21:26:15'  
> GROUP BY second ORDER BY second;

ClickHouse observed_at is UTC. The NAVProxy log used local-looking timestamps (15:25) while telemetry displayed 21:25 UTC, a six-hour difference. Verify logger timezone and clock configuration before treating event timestamps as exactly aligned; the difference was not resolved in this session.

# 6. Recorded regression — 6 November 2026

| Item                               | Observed result                          |
|------------------------------------|------------------------------------------|
| FER                                | 01a1b2be-2b38-7b5d-96da-69f7ca301621     |
| Profile                            | 01a192f3-afae-7992-9eee-b823930ac822     |
| Route / segment                    | 01a1916b-0cd9-7357-83a2-aa8e28ccb1b3 / 1 |
| Governed / target speed            | 14.67 / 7.335 ft/s                       |
| Valid measurements                 | 5 / 5 attempts                           |
| Per-attempt deceleration (ft/s²)   | 2.591, 2.632, 2.635, 2.641, 2.640        |
| Mean / selected conservative value | 2.628 / 2.591 ft/s²                      |
| Profile persistence                | Verified true; active; 2.591 ft/s²       |
| Telemetry samples                  | 4,825                                    |
| Flight telemetry window (UTC)      | 21:23:13 to 21:39:18                     |
| Min / max / average speed          | 0 / 14.814 / 13.699 ft/s                 |

Telemetry at 21:25:43 showed approximately 7.084 ft/s, followed by recovery to approximately 14.65 ft/s at 21:25:48. Subsequent speeds remained near the 14.67 ft/s Flight Band target. The full-flight maximum was 14.814 ft/s, without the large overshoot seen before the speed-governance correction.

Result: PASS for the successful recalibration path, conservative convergence, persisted aircraft profile update, and observed governed-speed recovery. The exact timestamp alignment, failure path, and setup commands remain to be documented or separately tested.

# 7. Repeatability checklist

- Confirm aircraft configuration, SITL start position, FER calibration flag, eligible Route and segment.

- Start telemetry collector; confirm ClickHouse connectivity.

- Launch SITL and NAVProxy using the environment-specific commands.

- Submit a single calibration.request for the intended Route segment.

- Confirm five valid measurements and a “Calibration converged” log line.

- Verify selected value equals minimum of the converged five, each within ±10% of their mean.

- Confirm aircraft profile fields and sample count in Drupal.

- Query ClickHouse for the FER and inspect speed recovery and maximum overshoot.

- Record FER, aircraft/profile IDs, flight band, target speed, log times and test outcome.

# 8. Open documentation items

- Capture exact ArduPilot SITL launch command and rotor frame parameters used for this aircraft.

- Capture exact NAVProxy execution command and calibration.request transport/CLI invocation.

- Verify the log timezone relative to ClickHouse UTC and document conversion.

- Run and document calibration interruption/failure-path regression separately.

