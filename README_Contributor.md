## Working Directory and Manual Testing

DroneNav NAVProxy is designed to execute from the project root directory:

```text
api.dronenav.org/
```

The Flight Log API launches NAVProxy using `subprocess.Popen()` with the working directory (`cwd`) explicitly set to the project root. This ensures that Python package imports resolve exactly as they do in production.

When manually testing NAVProxy modules, always execute commands from the same project root directory. Doing so guarantees that the package hierarchy and import resolution match the normal runtime environment.

Example:

```bash
cd /home/dronenavcp/api.dronenav.org
python -m app.navproxy ...
```

Avoid executing package modules directly from subdirectories such as:

```text
app/navproxy/
```

Running from a subdirectory changes Python's module search path and may produce `ModuleNotFoundError` or relative import errors that do not occur during normal execution.

### Note

The `tooling/` utilities may still be executed directly from the `app/navproxy/` directory for isolated development and testing. However, any testing of the NAVProxy package itself should be performed from the project root so that the execution environment faithfully matches production.


