"""
Retrieve a Flight Execution Record and create a compiler input JSON file.

This utility is stored in:

    navproxy/tooling/

It accepts a Flight Execution Record ID, retrieves the corresponding FER from
the DroneNav API, and writes the compiler input file to the existing directory:

    navproxy/tooling/examples/

The output filename embeds the FER ID:

    fer_<flight_execution_id>.json

The generated document contains the complete FER and an empty command stream:

    {
        "flight_execution": {
            "flight_execution_id": "...",
            ...
        },
        "commands": []
    }

Usage from the NAVProxy project root:

    python tooling/build_fer_compiler_input.py \
        019f6bc9-b635-7a7f-95d9-e1f15fdadfb6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_BASE_URL = "http://api.dronenav.org/api"

# This file is located in navproxy/tooling.
TOOLING_DIRECTORY = Path(__file__).resolve().parent

# Compiler input files are written to navproxy/tooling/examples.
OUTPUT_DIRECTORY = TOOLING_DIRECTORY / "examples"


class CompilerInputError(RuntimeError):
    """Raised when the compiler input file cannot be generated."""


def retrieve_flight_execution(
    api_base_url: str,
    flight_execution_id: str,
) -> dict[str, Any]:
    """
    Retrieve one Flight Execution Record from the DroneNav API.

    The API requires both Accept and Content-Type headers for this request.
    """

    url = (
        f"{api_base_url.rstrip('/')}/flight-executions/"
        f"{flight_execution_id}"
    )

    request = Request(
        url=url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")

    except HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = ""

        message = (
            f"Flight Execution API returned HTTP {exc.code} "
            f"for FER {flight_execution_id}."
        )

        if error_body:
            message = f"{message}\nResponse: {error_body}"

        raise CompilerInputError(message) from exc

    except URLError as exc:
        raise CompilerInputError(
            "Unable to connect to the Flight Execution API: "
            f"{exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise CompilerInputError(
            "The Flight Execution API request timed out."
        ) from exc

    try:
        flight_execution = json.loads(response_body)

    except json.JSONDecodeError as exc:
        raise CompilerInputError(
            "The Flight Execution API returned invalid JSON."
        ) from exc

    if not isinstance(flight_execution, dict):
        raise CompilerInputError(
            "The Flight Execution API response must be a JSON object."
        )

    returned_flight_execution_id = flight_execution.get(
        "flight_execution_id"
    )

    if returned_flight_execution_id is None:
        raise CompilerInputError(
            "The Flight Execution API response does not contain "
            "flight_execution_id."
        )

    if str(returned_flight_execution_id) != flight_execution_id:
        raise CompilerInputError(
            "The Flight Execution API returned an unexpected FER. "
            f"Requested {flight_execution_id}, but received "
            f"{returned_flight_execution_id}."
        )

    return flight_execution


def build_compiler_input(
    flight_execution: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the combined FER and command-stream input document.

    The FER is preserved inside the flight_execution object. The commands
    array is intentionally empty so test command streams can be added manually.
    """

    return {
        "flight_execution": flight_execution,
        "commands": [],
    }


def build_output_path(
    flight_execution_id: str,
) -> Path:
    """
    Build the output path beneath navproxy/tooling/examples.

    Example:

        navproxy/tooling/examples/
            fer_019f6bc9-b635-7a7f-95d9-e1f15fdadfb6.json
    """

    return OUTPUT_DIRECTORY / f"fer_{flight_execution_id}.json"


def write_compiler_input(
    output_path: Path,
    compiler_input: dict[str, Any],
) -> None:
    """
    Write the compiler input file to the existing tooling/examples directory.

    The utility reports an error rather than creating an unexpected directory.
    """

    if not OUTPUT_DIRECTORY.exists():
        raise CompilerInputError(
            "The expected examples directory does not exist:\n"
            f"    {OUTPUT_DIRECTORY}"
        )

    if not OUTPUT_DIRECTORY.is_dir():
        raise CompilerInputError(
            "The expected examples path is not a directory:\n"
            f"    {OUTPUT_DIRECTORY}"
        )

    try:
        with output_path.open(
            mode="w",
            encoding="utf-8",
        ) as output_file:
            json.dump(
                compiler_input,
                output_file,
                indent=2,
                ensure_ascii=False,
            )
            output_file.write("\n")

    except OSError as exc:
        raise CompilerInputError(
            "Unable to write the compiler input file:\n"
            f"    {output_path}"
        ) from exc


def parse_arguments() -> argparse.Namespace:
    """Parse the FER ID and optional API base URL."""

    parser = argparse.ArgumentParser(
        description=(
            "Retrieve a Flight Execution Record and create a compiler "
            "input JSON file in tooling/examples."
        )
    )

    parser.add_argument(
        "flight_execution_id",
        help="UUID of the Flight Execution Record to retrieve.",
    )

    parser.add_argument(
        "--api-base-url",
        default=DEFAULT_API_BASE_URL,
        help=(
            "DroneNav API base URL. "
            f"Default: {DEFAULT_API_BASE_URL}"
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Retrieve the FER and write its compiler input file."""

    arguments = parse_arguments()

    output_path = build_output_path(
        flight_execution_id=arguments.flight_execution_id,
    )

    if output_path.exists():
        return 0

    try:
        flight_execution = retrieve_flight_execution(
            api_base_url=arguments.api_base_url,
            flight_execution_id=arguments.flight_execution_id,
        )

        compiler_input = build_compiler_input(
            flight_execution=flight_execution,
        )

        write_compiler_input(
            output_path=output_path,
            compiler_input=compiler_input,
        )

    except CompilerInputError as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        "Compiler input file created successfully:\n"
        f"    {output_path.resolve()}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

