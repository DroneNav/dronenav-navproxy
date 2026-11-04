from __future__ import annotations

import logging
import threading

from flask import Flask, jsonify

from app.navproxy.rms.collector import main as run_collector
from app.navproxy.rms.logging_config import configure_logging
from app.navproxy.rms.registry import registry


server_logger = logging.getLogger(
  "app.navproxy.rms.server"
)

app = Flask(__name__)

configure_logging()

app.logger.handlers.clear()

for handler in server_logger.handlers:
  app.logger.addHandler(handler)

app.logger.setLevel(logging.INFO)
app.logger.propagate = False

werkzeug_logger = logging.getLogger("werkzeug")

werkzeug_logger.handlers.clear()

for handler in server_logger.handlers:
  werkzeug_logger.addHandler(handler)

werkzeug_logger.setLevel(logging.INFO)
werkzeug_logger.propagate = False



@app.get("/api/rms/runtimes")
def list_runtimes():
  return jsonify({
    "runtimes": registry.list_active(),
  })


def start_collector():
  thread = threading.Thread(
    target=run_collector,
    name="rms-collector",
    daemon=True,
  )

  thread.start()

  server_logger.info("RMS collector thread started")


def main():
  start_collector()

  server_logger.info("RMS server starting")

  app.run(
    host="127.0.0.1",
    port=5051,
    debug=False,
    use_reloader=False,
  )


if __name__ == "__main__":
  main()

