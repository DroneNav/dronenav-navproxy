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

## Migration

After this package is installed under `app/navproxy/` and tested, the placeholder `navproxy_proxy_service.py` can be removed. Any scheduler or launcher command that currently invokes the placeholder should instead run:

```bash
python -m app.navproxy ...
```

The simulator preserves the current behavior:

1. Validate the Flight Execution and Flight Log.
2. Simulate pre-flight activity.
3. Transition the Flight Log to `in_flight`.
4. Notify Drupal that the Flight Plan is `active`.
5. Simulate flight.
6. Complete the Flight Log.
7. Complete scheduled Flight Executions while leaving reusable executions active.
8. Notify Drupal of the resulting Flight Plan status.

