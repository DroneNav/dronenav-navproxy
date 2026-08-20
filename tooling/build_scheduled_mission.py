from __future__ import annotations

from pathlib import Path
from typing import Any

from app.navproxy.tooling.mavlink_compiler import (
    compile_mavlink_command_stream,
)
from app.navproxy.tooling.mavlink_emitter import (
    emit_mission_stream,
    load_yaml_file,
)


DEFAULT_METADATA_PATH = (
    Path(__file__).parent
    / "metadata"
    / "mavlink_commands.yaml"
)


def build_scheduled_mission(
    compiler_ir: dict[str, Any],
) -> dict[str, Any]:
    """Build the native MAVLink mission stream from compiler IR."""

    metadata = load_yaml_file(
        DEFAULT_METADATA_PATH
    )

    compiled_stream = compile_mavlink_command_stream(
        metadata,
        compiler_ir,
    )

    return emit_mission_stream(
        compiled_stream,
    )


