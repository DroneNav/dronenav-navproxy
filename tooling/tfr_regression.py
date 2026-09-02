#!/usr/bin/env python3

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone

import requests

from app.services.tfr_service import (
    build_tfr_schedule_interval,
    get_tfr_aixm,
    get_tfrs,
    is_tfr_layer_schedule_active,
    parse_tfr_aixm,
)


SUPPORTED_GEOMETRY_OPERATIONS = {
    "BASE",
    "SUBTR",
}

SUPPORTED_GEOMETRY_TYPES = {
    "circle",
    "polygon",
}

SUPPORTED_ALTITUDE_REFERENCES = {
    "SURFACE",
    "AGL",
    "MSL",
    "FL",
}

SUPPORTED_SCHEDULE_TYPES = {
    "EXPLICIT_INTERVAL",
    "RECURRING",
    "OPEN_START",
    "OPEN_END",
    "TFR_VALIDITY",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_datetime(value):
    if value is None:
        return None

    parsed = datetime.fromisoformat(value)

    require(
        parsed.tzinfo is not None,
        f"Datetime is not timezone-aware: {value}",
    )

    return parsed.astimezone(timezone.utc)


def validate_discovery_tfr(tfr):
    require(
        isinstance(tfr, dict),
        "FAA WFS TFR is not a dictionary",
    )

    require(
        tfr.get("notam_id"),
        "FAA WFS TFR has no NOTAM ID",
    )

    require(
        tfr.get("geometry") is not None,
        f"{tfr.get('notam_id')} has no WFS geometry",
    )


def validate_identity(parsed, expected_notam_id):
    require(
        isinstance(parsed, dict),
        f"{expected_notam_id} normalized TFR is not a dictionary",
    )

    require(
        parsed.get("notam_id"),
        f"{expected_notam_id} has no normalized NOTAM ID",
    )

    require(
        parsed["notam_id"] == expected_notam_id,
        (
            f"NOTAM identity mismatch: requested "
            f"{expected_notam_id}, parsed {parsed['notam_id']}"
        ),
    )

    require(
        parsed.get("begins_at"),
        f"{expected_notam_id} has no begins_at",
    )

    begins_at = parse_datetime(
        parsed["begins_at"]
    )

    ends_at = parse_datetime(
        parsed.get("ends_at")
    )

    if ends_at is not None:
        require(
            ends_at > begins_at,
            (
                f"{expected_notam_id} validity ends "
                f"before or at its begin"
            ),
        )


def validate_geometry_component(
    notam_id,
    component,
    counters,
):
    require(
        isinstance(component, dict),
        f"{notam_id} geometry component is not a dictionary",
    )

    operation = component.get("operation")

    require(
        operation in SUPPORTED_GEOMETRY_OPERATIONS,
        (
            f"{notam_id} unsupported geometry operation: "
            f"{operation}"
        ),
    )

    counters["geometry_operations"][operation] += 1

    geometry = component.get("geometry")

    require(
        isinstance(geometry, dict),
        f"{notam_id} geometry component has no geometry",
    )

    geometry_type = geometry.get("type")

    require(
        geometry_type in SUPPORTED_GEOMETRY_TYPES,
        (
            f"{notam_id} unsupported geometry type: "
            f"{geometry_type}"
        ),
    )

    counters["geometry_types"][geometry_type] += 1
    counters["geometry_components"] += 1


def validate_altitude(
    notam_id,
    name,
    altitude,
):
    require(
        isinstance(altitude, dict),
        f"{notam_id} {name} altitude is not a dictionary",
    )

    value = altitude.get("value")

    require(
        value is not None,
        f"{notam_id} {name} altitude has no value",
    )

    try:
        float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{notam_id} invalid {name} altitude value: {value}"
        ) from exc

    require(
        altitude.get("unit"),
        f"{notam_id} {name} altitude has no unit",
    )

    reference = altitude.get(
        "resolved_reference"
    )

    require(
        reference in SUPPORTED_ALTITUDE_REFERENCES,
        (
            f"{notam_id} unsupported {name} altitude "
            f"reference: {reference}"
        ),
    )

    return reference


def validate_schedule(
    notam_id,
    layer,
    schedule,
    parsed,
    counters,
):
    require(
        isinstance(schedule, dict),
        f"{notam_id} normalized schedule is not a dictionary",
    )

    schedule_type = schedule.get("type")

    require(
        schedule_type in SUPPORTED_SCHEDULE_TYPES,
        (
            f"{notam_id} unsupported normalized "
            f"schedule type: {schedule_type}"
        ),
    )

    counters["schedule_types"][schedule_type] += 1
    counters["normalized_schedules"] += 1

    if schedule_type == "RECURRING":
        day = schedule.get("day")

        require(
            day in {
                "ANY",
                "MON",
                "TUE",
                "WED",
                "THU",
                "FRI",
                "SAT",
                "SUN",
            },
            (
                f"{notam_id} unsupported recurring "
                f"weekday: {day}"
            ),
        )

        return

    interval = build_tfr_schedule_interval(
        schedule,
        parsed["begins_at"],
        parsed.get("ends_at"),
    )

    require(
        isinstance(interval, dict),
        (
            f"{notam_id} non-recurring schedule "
            f"produced no interval"
        ),
    )

    begins_at = interval.get("begins_at")
    ends_at = interval.get("ends_at")

    require(
        begins_at is not None,
        f"{notam_id} schedule interval has no begin",
    )

    require(
        begins_at.tzinfo is not None,
        (
            f"{notam_id} schedule begin is "
            f"not timezone-aware"
        ),
    )

    if ends_at is None:
        counters["unbounded_intervals"] += 1
    else:
        require(
            ends_at.tzinfo is not None,
            (
                f"{notam_id} schedule end is "
                f"not timezone-aware"
            ),
        )

        require(
            ends_at >= begins_at,
            (
                f"{notam_id} schedule interval "
                f"ends before it begins"
            ),
        )

    counters["concrete_intervals"] += 1


def validate_layer(
    notam_id,
    layer,
    parsed,
    counters,
):
    require(
        isinstance(layer, dict),
        f"{notam_id} layer is not a dictionary",
    )

    lower_reference = validate_altitude(
        notam_id,
        "lower",
        layer.get("lower_altitude"),
    )

    upper_reference = validate_altitude(
        notam_id,
        "upper",
        layer.get("upper_altitude"),
    )

    counters["altitude_reference_pairs"][
        (
            lower_reference,
            upper_reference,
        )
    ] += 1

    schedules = layer.get(
        "normalized_schedules"
    )

    require(
        isinstance(schedules, list),
        (
            f"{notam_id} layer has no "
            f"normalized_schedules list"
        ),
    )

    require(
        schedules,
        (
            f"{notam_id} layer has no "
            f"normalized schedules"
        ),
    )

    for raw_schedule in layer.get(
        "schedules",
        [],
    ):
        time_reference = raw_schedule.get(
            "time_reference"
        )

        require(
            time_reference == "UTC",
            (
                f"{notam_id} unsupported FAA "
                f"time reference: {time_reference}"
            ),
        )

    for schedule in schedules:
        validate_schedule(
            notam_id,
            layer,
            schedule,
            parsed,
            counters,
        )

    #
    # Exercise the unified temporal evaluator as well.
    #
    # We are not asserting whether the layer must be active
    # "now"; only that the evaluator can safely interpret
    # the layer at a timezone-aware UTC datetime.
    #
    result = is_tfr_layer_schedule_active(
        layer,
        datetime.now(timezone.utc),
        parsed["begins_at"],
        parsed.get("ends_at"),
    )

    require(
        isinstance(result, bool),
        (
            f"{notam_id} layer schedule evaluator "
            f"did not return bool"
        ),
    )

    counters["layers"] += 1


def validate_airspace_usage(
    notam_id,
    usage,
    parsed,
    counters,
):
    require(
        isinstance(usage, dict),
        f"{notam_id} AirspaceUsage is not a dictionary",
    )

    require(
        usage.get("airspace_id"),
        f"{notam_id} AirspaceUsage has no airspace_id",
    )

    components = usage.get(
        "geometry_components"
    )

    require(
        isinstance(components, list),
        (
            f"{notam_id} AirspaceUsage has no "
            f"geometry_components list"
        ),
    )

    require(
        components,
        (
            f"{notam_id} AirspaceUsage has no "
            f"geometry components"
        ),
    )

    for component in components:
        validate_geometry_component(
            notam_id,
            component,
            counters,
        )

    layers = usage.get("layers")

    require(
        isinstance(layers, list),
        (
            f"{notam_id} AirspaceUsage has "
            f"no layers list"
        ),
    )

    require(
        layers,
        f"{notam_id} AirspaceUsage has no layers",
    )

    for layer in layers:
        validate_layer(
            notam_id,
            layer,
            parsed,
            counters,
        )

    counters["airspace_usages"] += 1


def validate_parsed_tfr(
    notam_id,
    parsed,
    counters,
):
    validate_identity(
        parsed,
        notam_id,
    )

    usages = parsed.get(
        "airspace_usages"
    )

    require(
        isinstance(usages, list),
        (
            f"{notam_id} normalized TFR has "
            f"no airspace_usages list"
        ),
    )

    require(
        usages,
        f"{notam_id} has no AirspaceUsage",
    )

    for usage in usages:
        validate_airspace_usage(
            notam_id,
            usage,
            parsed,
            counters,
        )

    counters["parsed_tfrs"] += 1


def run_population_regression():
    print()
    print("FAA TFR POPULATION REGRESSION")
    print("=" * 72)

    tfrs = get_tfrs()

    require(
        isinstance(tfrs, list),
        "get_tfrs() did not return a list",
    )

    require(
        tfrs,
        "FAA WFS returned no TFRs",
    )

    discovery_failures = []

    for index, tfr in enumerate(tfrs):
        try:
            validate_discovery_tfr(tfr)
        except Exception as exc:
            discovery_failures.append(
                (
                    f"WFS feature {index}",
                    str(exc),
                )
            )

    if discovery_failures:
        return None, discovery_failures

    notam_ids = sorted({
        tfr["notam_id"]
        for tfr in tfrs
        if tfr.get("notam_id")
    })

    require(
        notam_ids,
        "FAA WFS returned no NOTAM identities",
    )

    counters = {
        "parsed_tfrs": 0,
        "airspace_usages": 0,
        "layers": 0,
        "geometry_components": 0,
        "normalized_schedules": 0,
        "concrete_intervals": 0,
        "unbounded_intervals": 0,
        "geometry_operations": Counter(),
        "geometry_types": Counter(),
        "altitude_reference_pairs": Counter(),
        "schedule_types": Counter(),
    }

    failures = []

    for index, notam_id in enumerate(
        notam_ids,
        start=1,
    ):
        print(
            f"\rParsing {index}/{len(notam_ids)} "
            f"{notam_id}",
            end="",
            flush=True,
        )

        try:
            aixm_data = get_tfr_aixm(
                notam_id
            )

            require(
                aixm_data,
                (
                    f"{notam_id} AIXM download "
                    f"was empty"
                ),
            )

            parsed = parse_tfr_aixm(
                aixm_data
            )

            validate_parsed_tfr(
                notam_id,
                parsed,
                counters,
            )

        except Exception as exc:
            failures.append(
                (
                    notam_id,
                    str(exc),
                )
            )

    print()

    summary = {
        "wfs_features": len(tfrs),
        "unique_notams": len(notam_ids),
        **counters,
    }

    return summary, failures


def run_http_smoke_test(api_url):
    endpoint = (
        api_url.rstrip("/")
        + "/api/tfrs"
    )

    print()
    print("DRONENAV HTTP API SMOKE TEST")
    print("=" * 72)
    print(endpoint)

    response = requests.get(
        endpoint,
        timeout=30,
    )

    response.raise_for_status()

    payload = response.json()

    require(
        isinstance(payload, dict),
        "GET /api/tfrs did not return JSON object",
    )

    require(
        "tfrs" in payload,
        "GET /api/tfrs response has no tfrs key",
    )

    require(
        isinstance(payload["tfrs"], list),
        "GET /api/tfrs tfrs is not a list",
    )

    require(
        payload["tfrs"],
        "GET /api/tfrs returned an empty list",
    )

    for tfr in payload["tfrs"]:
        validate_discovery_tfr(tfr)

    print(
        "HTTP status:",
        response.status_code,
    )

    print(
        "TFRs returned:",
        len(payload["tfrs"]),
    )

    print("HTTP API SMOKE TEST PASSED")


def print_counter(title, counter):
    print()
    print(title)

    for key, count in sorted(
        counter.items(),
        key=lambda item: str(item[0]),
    ):
        if isinstance(key, tuple):
            key = " -> ".join(key)

        print(
            f"    {key:<24} {count}"
        )


def print_summary(summary):
    print()
    print("REGRESSION SUMMARY")
    print("=" * 72)

    print(
        f"WFS features:             "
        f"{summary['wfs_features']}"
    )

    print(
        f"Unique NOTAMs:            "
        f"{summary['unique_notams']}"
    )

    print(
        f"Parsed TFRs:              "
        f"{summary['parsed_tfrs']}"
    )

    print(
        f"Airspace usages:          "
        f"{summary['airspace_usages']}"
    )

    print(
        f"Layers:                   "
        f"{summary['layers']}"
    )

    print(
        f"Geometry components:      "
        f"{summary['geometry_components']}"
    )

    print(
        f"Normalized schedules:     "
        f"{summary['normalized_schedules']}"
    )

    print(
        f"Concrete intervals:       "
        f"{summary['concrete_intervals']}"
    )

    print(
        f"Unbounded intervals:      "
        f"{summary['unbounded_intervals']}"
    )

    print_counter(
        "GEOMETRY OPERATIONS",
        summary["geometry_operations"],
    )

    print_counter(
        "GEOMETRY TYPES",
        summary["geometry_types"],
    )

    print_counter(
        "ALTITUDE REFERENCE PAIRS",
        summary["altitude_reference_pairs"],
    )

    print_counter(
        "SCHEDULE TYPES",
        summary["schedule_types"],
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "DroneNav FAA TFR regression test"
        )
    )

    parser.add_argument(
        "--api-url",
        help=(
            "Optional DroneNav API base URL. "
            "When supplied, GET /api/tfrs is "
            "smoke-tested before the full FAA "
            "population regression."
        ),
    )

    args = parser.parse_args()

    failures = []

    try:
        if args.api_url:
            run_http_smoke_test(
                args.api_url
            )

    except Exception as exc:
        failures.append(
            (
                "HTTP API",
                str(exc),
            )
        )

    summary = None

    try:
        summary, population_failures = (
            run_population_regression()
        )

        failures.extend(
            population_failures
        )

    except Exception as exc:
        failures.append(
            (
                "Population regression",
                str(exc),
            )
        )

    if summary is not None:
        print_summary(summary)

    print()
    print("=" * 72)

    if failures:
        print(
            f"FAA TFR REGRESSION FAILED: "
            f"{len(failures)} failure(s)"
        )

        for source, error in failures:
            print()
            print(source)
            print(f"    {error}")

        return 1

    print("FAA TFR REGRESSION PASSED")

    return 0


if __name__ == "__main__":
    sys.exit(main())
