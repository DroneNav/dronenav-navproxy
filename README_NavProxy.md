# NAVProxy

NAVProxy is the integration point between the DroneNav platform and the flight-controller communications layer.

This initial project structure migrates the existing simulated NAVProxy process without changing its behavior. It continues to use the shared DroneNav Python environment, database configuration, and platform constants.

## Initial Structure

```text
navproxy/
├── __init__.py
├── __main__.py
├── execution_service.py
├── flight_repository.py
├── drupal_client.py
├── simulator.py
└── settings.py
```

- `__main__.py` launches one NAVProxy process.
- `execution_service.py` coordinates the flight lifecycle.
- `flight_repository.py` reads and updates Flight Execution and Flight Log data.
- `drupal_client.py` sends Flight Plan lifecycle callbacks.
- `simulator.py` provides the initial simulated flight-controller behavior.
- `settings.py` contains NAVProxy-specific runtime settings.

## Shared DroneNav Resources

NAVProxy intentionally uses:

```python
from app.config.database import engine
from app.config.constants import ...
```

The NAVProxy repository may be separate while remaining under `app/navproxy/` so that it uses the same Python environment, DroneNav configuration, and PostgreSQL database.

## Running the Simulator

From the root of the DroneNav API project:

```bash
python -m app.navproxy \
  --flight-execution-id <flight-execution-uuid> \
  --flight-log-id <flight-log-uuid>
```

Optional timing overrides:

```bash
python -m app.navproxy \
  --flight-execution-id <flight-execution-uuid> \
  --flight-log-id <flight-log-uuid> \
  --preflight-seconds 5 \
  --flight-seconds 10
```

## Manual Simulator Launch

NAVProxy normally runs against the configured MAVLink flight controller. For development and testing, a scheduled Flight Execution can be launched explicitly using the NAVProxy simulator without changing the normal system configuration.

Use:

```bash
python -m app.navproxy.tooling.launch_simulator_flight \
  --flight-execution-id <FLIGHT_EXECUTION_UUID>
```

The manual simulator launcher:

1. Loads the specified scheduled Flight Execution.
2. Atomically claims the Flight Execution and creates its Flight Log using the same launch path used by the scheduler.
3. Launches NAVProxy with `NAVPROXY_FC_MODE=simulator` for that NAVProxy process only.
4. Performs normal pre-flight validation.
5. Transitions the Flight Log to `in_flight`.
6. Notifies Drupal that the Flight Plan is `active`.
7. Generates simulated flight-controller telemetry from the compiled Flight Execution.
8. Simulates landing and aircraft disarm.
9. Performs normal post-flight validation.
10. Completes the Flight Log and scheduled Flight Execution.
11. Notifies Drupal that the Flight Plan is `completed`.

The simulator override applies only to the NAVProxy process launched by this tool. It does not change the configured default flight-controller mode.

The production scheduler continues to launch NAVProxy normally using the configured flight-controller mode. With `NAVPROXY_FC_MODE=mavlink` configured as the normal environment setting, scheduler-launched Flight Executions use the MAVLink flight-controller integration.

Scheduled Flight Executions are atomically claimed. A Flight Execution that has already been claimed by the scheduler or another launcher cannot be reused by the manual simulator launcher.

