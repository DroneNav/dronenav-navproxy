from __future__ import annotations

from typing import Any

from pymavlink import mavutil

from app.navproxy.fc_adapters.ardupilot import (
    encode_failsafe_recovery_map,
)

from io import BytesIO

from pymavlink.mavftp import (
    FtpError,
    MAVFTP,
)


FAILSAFE_RECOVERY_PATH = "@FAILSAFE/recovery.map"


class FailsafeRecoveryProgrammingError(RuntimeError):
    """Raised when ArduPilot failsafe recovery cannot be programmed."""


def build_failsafe_recovery_payload(
    compiler_ir: dict[str, Any],
) -> bytes:
    """Build the ArduPilot failsafe recovery-map payload."""

    mission = compiler_ir.get("mission")

    if not isinstance(mission, dict):
        raise FailsafeRecoveryProgrammingError(
            "Compiler IR does not contain a mission."
        )

    jump_map = mission.get("failsafe_jump_map")

    if not isinstance(jump_map, list) or not jump_map:
        raise FailsafeRecoveryProgrammingError(
            "Compiler IR does not contain a failsafe jump map."
        )

    try:
        return encode_failsafe_recovery_map(
            jump_map
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FailsafeRecoveryProgrammingError(
            "Failsafe recovery jump map could not be encoded."
        ) from exc


class FailsafeRecoveryReadback:
    """Capture an ArduPilot failsafe recovery FTP download in memory."""

    def __init__(self, ftp: MAVFTP) -> None:
        self.ftp = ftp
        self.buffer = BytesIO()

    def __call__(self, file_handle) -> None:
        if file_handle is None:
            return

        self.buffer.write(
            file_handle.read()
        )

        # Prevent pymavlink from materializing the completed
        # FTP download as a local file.
        self.ftp.filename = None

    def getvalue(self) -> bytes:
        return self.buffer.getvalue()


def program_failsafe_recovery_map(
    *,
    connection: mavutil.mavfile,
    compiler_ir: dict[str, Any],
    timeout: float = 10.0,
) -> None:
    """Program and verify ArduPilot's persistent failsafe recovery map."""

    payload = build_failsafe_recovery_payload(
        compiler_ir
    )

    ftp = MAVFTP(
        connection,
        connection.target_system,
        connection.target_component,
    )

    upload_result = ftp.cmd_put(
        [
            "recovery.map",
            FAILSAFE_RECOVERY_PATH,
        ],
        fh=BytesIO(payload),
    )

    if upload_result.return_code != FtpError.Success:
        raise FailsafeRecoveryProgrammingError(
            "ArduPilot rejected failsafe recovery FTP upload startup."
        )

    upload_result = ftp.process_ftp_reply(
        "CreateFile",
        timeout=timeout,
    )

    if (
        upload_result is None
        or upload_result.return_code != FtpError.Success
    ):
        raise FailsafeRecoveryProgrammingError(
            "ArduPilot failed to program the failsafe recovery map."
        )

    readback = FailsafeRecoveryReadback(ftp)

    read_result = ftp.cmd_get(
        [
            FAILSAFE_RECOVERY_PATH,
        ],
        callback=readback,
    )

    if read_result.return_code != FtpError.Success:
        raise FailsafeRecoveryProgrammingError(
            "ArduPilot rejected failsafe recovery FTP read-back."
        )

    read_result = ftp.process_ftp_reply(
        "OpenFileRO",
        timeout=timeout,
    )

    if (
        read_result is None
        or read_result.return_code != FtpError.Success
    ):
        raise FailsafeRecoveryProgrammingError(
            "ArduPilot failsafe recovery map could not be read back."
        )

    if readback.getvalue() != payload:
        raise FailsafeRecoveryProgrammingError(
            "ArduPilot failsafe recovery map read-back validation failed."
        )


