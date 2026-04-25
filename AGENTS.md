# AGENTS.md

## Device Workflow

This project runs on a MicroPython Inky Frame / Pico W device. `main.py` is the boot entrypoint and runs automatically when the device starts.

Use `mpremote` for iteration instead of Thonny.

Common commands:

```bash
mpremote ls
mpremote cp main.py :main.py
mpremote cp housekeeping.py :housekeeping.py
mpremote cp main.py :main.py + cp housekeeping.py :housekeeping.py + reset
mpremote repl
mpremote run main.py
```

Notes:

- `mpremote run main.py` runs the local file from RAM without copying it to the device.
- Copy both `main.py` and `housekeeping.py` to the device when changing boot behavior.
- In `mpremote repl`, use `Ctrl-]` to exit back to the shell.
- `Ctrl-C` interrupts code running on the device.
- `Ctrl-D` soft-reboots the device.
