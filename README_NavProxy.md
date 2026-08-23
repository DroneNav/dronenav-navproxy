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


## RabbitMQ Telemetry Collector

NAVProxy publishes normalized flight telemetry to RabbitMQ during flight execution. The MQ Collector is a development and diagnostic utility that consumes these telemetry messages so the NAVProxy telemetry stream can be observed directly.

Telemetry is published using the following RabbitMQ topology:

```text
Host:        rabbitmq.dronenav.org
Port:        5671 (AMQPS/TLS)
Virtual host: prototype
Exchange:    dronenav.telemetry
Routing key: telemetry.raw
Queue:       dronenav.telemetry.raw
```

### Starting the MQ Collector

From the root of the DroneNav API project:

```bash
python -m app.navproxy.tooling.consume_telemetry
```

The collector connects to RabbitMQ and consumes messages from:

```text
dronenav.telemetry.raw
```

When successfully connected, it reports:

```text
Consuming telemetry from dronenav.telemetry.raw. Press Ctrl+C to stop.
```

Leave the collector running while executing a simulator or MAVLink/SITL flight.

Stop the collector with:

```text
Ctrl+C
```

### RabbitMQ Credentials

The collector uses application credentials supplied through environment variables. RabbitMQ administrative credentials must not be used by NAVProxy or the telemetry collector.

The appropriate telemetry consumer credentials must be available in the runtime environment before starting the collector.

Credentials must not be committed to the DroneNav repository.

### Telemetry Output

Each consumed message represents a normalized NAVProxy telemetry observation associated with a Flight Execution and Flight Log.

Telemetry currently includes fields such as:

```text
flight_execution_id
flight_id
recorded_at

telemetry:
    latitude
    longitude
    relative_altitude_ft
    absolute_altitude_ft
    armed
    heartbeat_active
    mission_sequence
    battery_percent
    navigation_health
    vehicle_health
```

The telemetry values exposed through RabbitMQ are DroneNav-normalized values. Flight-controller-specific interpretation is performed by the appropriate flight-controller adapter before the telemetry message is published.

For example, the ArduPilot adapter converts native MAVLink heartbeat, battery, and navigation information into the platform-neutral telemetry semantics consumed by NAVProxy.

### Development Use

The MQ Collector is currently intended primarily for development, integration testing, and telemetry inspection.

A typical SITL test workflow is:

```text
1. Start ArduPilot SITL.
2. Start the MQ Collector.
3. Launch or schedule a Flight Execution.
4. Observe telemetry messages during the flight.
5. Verify aircraft and NAVProxy state transitions.
6. Stop the collector with Ctrl+C when testing is complete.
```

The collector is useful for validating telemetry such as:

```text
armed
battery_percent
navigation_health
mission_sequence
position
altitude
```

For example, during a normal SITL flight the `armed` state should transition approximately as follows:

```text
before launch  -> false
in flight      -> true
after landing  -> false
```

### Queue Consumption

The MQ Collector is a real RabbitMQ consumer, not a passive queue viewer.

Messages successfully consumed and acknowledged by the collector are removed from the queue. Therefore, starting the collector against a queue containing previously accumulated telemetry will consume those queued messages.

The collector should consequently be treated as a development consumer of the telemetry stream rather than as a permanent telemetry storage mechanism.

Long-term telemetry persistence and analysis are separate concerns from RabbitMQ transport.

