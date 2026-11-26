# Fuel Assistant

A Python-based fuel management dashboard and automation toolkit for tracking fuel-card activity, vehicle data, routes, tank levels, and operating costs.

## Features

- **Fleet dashboard** — Web interface for monitoring fleet and fuel activity
- **Fuel-card agent** — Handles fuel-card requests in driver Telegram groups
- **Card checker** — Reviews active cards and fleet-truck assignments
- **Automatic data collection** — Imports and processes fuel, accounting, EFS, and vehicle data
- **Route and location analysis** — Supports nearby-store, road-rule, and route recommendations
- **Driver and fleet reporting** — Tracks habits, mileage, load, evidence, and operational outcomes
- **Scheduled Windows tasks** — Includes batch launchers for Windows-based operation
- **Comprehensive tests** — pytest suite covering the dashboard, cards, integrations, and business rules

## Technology

- Python
- JavaScript
- HTML and CSS
- SQLite-style local data storage
- HTTP and WebSocket integrations
- Telegram through Telethon
- Claude Agent SDK
- pytest

## Repository Layout

```text
src/        Backend application modules and entry points
web/        Dashboard HTML, CSS, JavaScript, and vendor assets
tests/      Automated pytest suite
doc/        Plans, documentation, and project notes
run.bat     Launches the dashboard and restarts it if it stops
run_agent.bat
            Runs the fuel-card agent
run_checker.bat
            Runs the scheduled fuel-card checker
```

## Requirements

- Windows for the included `.bat` launchers
- Python 3.10 or newer recommended
- A virtual environment
- The dependencies listed in `requirements.txt`

## Installation

Clone the repository and create a virtual environment:

```powershell
git clone https://github.com/payable-tech/fuel-assistant.git
cd fuel-assistant

py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a local `.env` file as needed for credentials and integration settings. Keep credentials out of source control.

## Running the Dashboard

```powershell
python src/main.py serve
```

To run it with automatic restart:

```powershell
run.bat
```

The included script restarts the dashboard 30 seconds after an unexpected exit.

## Commands

Additional commands are available through the application entry point:

```powershell
python src/main.py --help
```

Specialized launchers include:

```powershell
# Fuel-card agent
python src/main.py card-agent

# Fuel-card checker
python src/main.py card-check

# Initial agent login setup
python src/main.py agent-login

# Initial card-checker login setup
python src/main.py checker-login
```

## Testing

Run the full test suite:

```powershell
pytest
```

Run a specific test module:

```powershell
pytest tests/test_card_agent.py
```

## Windows Automation

The project includes several Windows launch scripts:

- `run.bat` — Starts the dashboard and restarts it automatically
- `run_agent.bat` — Starts and supervises the card agent
- `run_checker.bat` — Runs the card-check workflow once

The repository documentation also describes scheduled Task Scheduler usage for periodic card checks and other maintenance jobs.

## Configuration and Data

Runtime data, credentials, logs, and integration state should remain outside version control. The repository ignores local environment and data-related files through `.gitignore`.

The card agent requires a Claude Code login on the host PC. The EManager and card-check workflows may also require separate one-time browser login setup.

## Documentation

Additional project documentation is available in the [`doc`](./doc) directory:

- [`doc/PLAN.md`](./doc/PLAN.md)
- [`doc/LOOP.md`](./doc/LOOP.md)
- [`doc/visions.md`](./doc/visions.md)

## License

No license has currently been specified in the repository.
