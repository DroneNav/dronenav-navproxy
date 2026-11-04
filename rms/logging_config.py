from __future__ import annotations

import logging
from pathlib import Path


def configure_logging() -> None:
  log_directory = Path.home() / "logs"
  log_directory.mkdir(
    parents=True,
    exist_ok=True,
  )

  formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
  )

  for component, filename in (
    ("server", "navproxy-rms-server.log"),
    ("collector", "navproxy-rms-collector.log"),
  ):
    logger = logging.getLogger(
      f"app.navproxy.rms.{component}"
    )
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
      continue

    handler = logging.FileHandler(
      log_directory / filename
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


