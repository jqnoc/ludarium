# Ludarium

Ludarium is a self-contained Electron desktop application for tracking a
personal video game library and play sessions.

## Stack

- Electron for the desktop shell
- Flask for the local backend
- SQLite for per-user data
- Jinja templates and vanilla JavaScript

## Development

Requirements:

- Node.js 18+
- Python 3.12+

Install the JavaScript and Python dependencies:

```powershell
npm install
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the desktop app with:

```powershell
npm start
```

On Windows, you can also double-click `run-ludarium.bat` or
`Ludarium.vbs`. The VBS launcher starts the Electron app without opening a
console window.

The backend can also be run directly with `.venv\Scripts\python.exe app.py`.
Development data is stored in `data/`; set `LUDARIUM_DATA_DIR` to use another
directory. Packaged builds use the same SQLite schema and per-user storage
model as the development app. Packaged builds store data under
`%APPDATA%\Ludarium\data` unless `LUDARIUM_DATA_DIR` is set.
The last selected user is remembered between launches; use “Switch user” from
the application header when you need to change profiles.

## Troubleshooting

The Electron shell disables hardware acceleration for compatibility with
systems whose graphics drivers leave a native-background window unpainted.
The renderer also retries failed local-page loads and displays a retry screen
instead of leaving the window blank. If an older portable executable is still
running, close it fully before launching a newly built package.
Ludarium - A personal video game catalogue and play-session tracker.
