# Ludarium — Agent Directives

These directives apply whenever working on the Ludarium project. They keep
the Electron shell, Flask backend, SQLite data model, and game/session UI
consistent.

---

## 1. Project Overview

Ludarium is a self-contained Electron desktop application for tracking a
personal video game library and play sessions. The backend is a monolithic
Flask application (`app.py`) using raw SQLite queries, Jinja templates, and
vanilla JavaScript. Development runs the Flask app through Electron; Windows
portable builds run a PyInstaller backend executable.

There is currently no repository test suite. Verification uses syntax checks,
Flask test-client smoke/integration checks, and manual Electron/package
verification.

| Aspect | Value |
|--------|-------|
| Electron entry point | `main.js` |
| Flask entry point | `app.py` |
| Preload bridge | `preload.js` |
| Packaged backend | `build/backend/ludarium-backend.exe` |
| Version | `APP_VERSION` in `app.py` and `version` in `package.json` |
| Database | Per-user SQLite databases, WAL mode, foreign keys enabled |
| Python | Use the project virtual environment; documented target is Python 3.12+ |
| Node.js | 18+ |
| Python dependencies | Flask, Pillow, PyInstaller |
| Preferred Flask port | `48742`, with a dynamic fallback |
| Development start | `npm start` |
| Windows launchers | `run-ludarium.bat` or `Ludarium.vbs` |
| Portable build | `npm.cmd run build` |

Use the repository virtual environment rather than assuming that the system
Python contains Flask or PyInstaller.

---

## 2. Architecture

### 2.1 Electron shell

`main.js` is the Electron main process. It:

1. Finds a free local TCP port, preferring `48742`.
2. Starts `app.py` in development or `ludarium-backend.exe` when packaged.
3. Passes `LUDARIUM_PORT`, `LUDARIUM_ELECTRON`, and `LUDARIUM_DATA_DIR` to the backend.
4. Polls until Flask accepts connections.
5. Opens a frameless maximized `BrowserWindow` at the local Flask URL.
6. Uses a splash window while the backend starts.
7. Disables hardware acceleration for Windows renderer compatibility.
8. Retries failed renderer loads and shows a visible error/retry page instead of
   leaving only the native background visible.
9. Handles external links through the system browser.
10. Calls `/shutdown-backup` before quitting through the renderer.

The packaged default data directory is `%APPDATA%\Ludarium\data`. Development
defaults to `data\`; `LUDARIUM_DATA_DIR` overrides either location.

`preload.js` must remain a narrow, sandbox-safe `contextBridge` exposing only
window controls and state events. Do not enable `nodeIntegration` in the
renderer or expose filesystem/process APIs.

### 2.2 Monolithic Flask backend

All backend behavior currently lives in `app.py`: configuration, user and
library selection, SQLite schema bootstrap, helpers, media processing, routes,
statistics, activity tracking, and backup handling.

- Use raw parameterized SQL through `sqlite3`; there is no ORM.
- `get_db()` stores the per-request connection in Flask `g`.
- User and library access must go through the existing validation helpers.
- `RESOURCE_DIR` supports both source execution and PyInstaller's `_MEIPASS`.
- Preserve the existing route/template architecture unless a structural change
  is explicitly requested.
- Surface database, media, and backup failures explicitly; do not silently
  return success-shaped fallbacks.

### 2.3 Local storage and backups

| Data | Location |
|------|----------|
| User registry | `DATA_DIR\users.json` |
| User database | `DATA_DIR\<sanitized-username>.db` |
| Default backups | `DATA_DIR\backups\<sanitized-username>\` |
| Packaged default root | `%APPDATA%\Ludarium\data` |

SQLite connections enable WAL mode and foreign-key enforcement. Backups use the
SQLite Online Backup API and retain the five most recent
`ludarium_<timestamp>.db` files for each user. Cover originals and thumbnails
are stored in the `game_media` table.

Never commit user databases, `users.json`, cover blobs, backups, `data\`,
`build\`, `dist\`, `.venv\`, or `node_modules\`.

### 2.4 Database and schema changes

The current schema is initialized by `_init_schema()` in `app.py` and contains
the following normalized tables:

```text
libraries       (id, name, slug)
games           (id TEXT, title, release metadata, status, ownership,
                 platforms-related metadata, dates, rating, notes, library_id)
platforms       (id, name, slug)
game_platforms  (game_id, platform_id, is_primary)
tags            (id, name, slug)
game_tags       (game_id, tag_id)
game_media      (id, game_id, kind, blob, mime, thumbnail, content_hash,
                 is_primary)
ratings         (game_id, dimension_key, value)
sessions        (id, game_id, date/time, duration, platform, type, mode,
                 progress, chapter/objective, participants, location,
                 achievements, mood, notes, timestamps)
status_history  (id, game_id, status, changed_at)
```

When changing the schema:

- Keep foreign keys and cascade behavior correct.
- Preserve existing user databases; do not drop tables or silently discard data.
- Make schema changes idempotent and compatible with both a fresh database and
  an existing database.
- Add a migration/helper path in `app.py` when `ALTER TABLE` or data backfill
  is required; do not rely on a fresh install.
- Update all affected SQL helpers, templates, forms, and verification checks.
- Test at least one fresh database and one database containing existing data.

---

## 3. Domain Rules

### 3.1 Game statuses

The canonical statuses are defined by `STATUS_LABELS` and `STATUS_VALUES`:

| Value | Display label |
|-------|---------------|
| `wishlist` | Wishlist |
| `backlog` | Backlog |
| `playing` | Playing |
| `completed` | Completed |
| `abandoned` | Abandoned |
| `replaying` | Replaying |

When adding or changing a status, update the backend constants, forms and
filters, status badges and CSS variables, statistics/activity handling, and
both language dictionaries where the status is displayed.

### 3.2 Sessions and progress

Supported session types are `regular`, `multiplayer`, `replay`, `completion`,
and `achievement`. Supported modes are `solo`, `local_coop`, `online`,
`competitive`, and `mixed`.

Session invariants:

- Session duration is stored as integer `duration_seconds`.
- Dates use ISO `YYYY-MM-DD`; times use the existing form conventions.
- A first session fills a blank game's `start_date`.
- A `completion` session or progress of at least 100 percent marks the game
  `completed` and records its completion date.
- Session and platform IDs must be validated against the active user's library
  before writes.
- Statistics and activity queries must remain scoped to the selected library.

### 3.3 Ratings and relationships

Ratings are normalized by dimension. Current dimensions are `gameplay`,
`story`, `visuals`, `audio`, `performance`, `accessibility`, and
`replayability`.

Platforms and tags are normalized many-to-many relationships. Reuse the
existing named-relation helpers instead of duplicating parsing or insert logic.
Game IDs are UUID strings; platform, tag, media, session, and history IDs are
integer keys unless the schema says otherwise.

### 3.4 Users and libraries

The active user is validated from the `ludarium_user` cookie against
`users.json`; the active library is selected through the
`ludarium_library` cookie. Every game, session, statistic, index count, and
detail query must respect the active library where applicable.

Do not add one-off seed data or import logic to `app.py`. For a user-requested
data import, use a temporary standalone script against the selected SQLite
database, guard against duplicates, run it once, and remove it afterward.

---

## 4. Frontend Conventions

### 4.1 Styling

The design system is in `static/style.css`:

- CSS variables use the `--lu-` prefix.
- The visual language uses deep navy/indigo, teal actions, and coral accents.
- Both light and dark themes are supported through
  `html[data-theme="dark"]`.
- Reuse existing cards, badges, forms, tables, empty states, responsive
  breakpoints, and spacing variables before adding new patterns.
- Preserve Electron drag/no-drag behavior in the frameless header.

### 4.2 Internationalisation

English and Spanish translations live in `static/i18n.js`; the preference is
stored under `ludarium_lang`.

When adding user-facing text:

- Add the key to both `en` and `es`.
- Use `data-i18n`, `data-i18n-placeholder`, or
  `window.ludariumTranslate()` rather than hard-coded duplicate UI strings.
- Check language switching on the affected page.

### 4.3 Templates and media

`templates/base.html` owns shared navigation, library selection, user controls,
theme/language controls, window controls, flash messages, modal handling, and
backup shutdown UI. Page templates should extend it rather than reimplementing
the shell.

Use thumbnail endpoints for catalog/list views and full cover endpoints only
where detail display requires them. Keep upload validation and image processing
in the existing backend helpers.

---

## 5. Route Map

### Pages and write routes

| URL | Method | Purpose |
|-----|--------|---------|
| `/` | GET | Dashboard for the active library |
| `/library` | GET | Searchable game catalog |
| `/game/new` | GET, POST | Create a game |
| `/game/<id>` | GET | Game detail and session history |
| `/game/<id>/edit` | GET, POST | Edit a game |
| `/game/<id>/delete` | POST | Delete a game |
| `/sessions` | GET | Filtered session history and quick logging |
| `/session/new` | POST | Create a play session |
| `/session/<id>/edit` | GET, POST | Edit a play session |
| `/session/<id>/delete` | POST | Delete a play session |
| `/stats` | GET | Play-time and library statistics |
| `/activity` | GET | Activity feed, heatmap, and streaks |
| `/index` | GET | Browse platforms, genres, creators, series, and tags |
| `/users` | GET | User selection/creation page |
| `/users/create` | POST | Create a user |
| `/users/switch` | POST | Switch user |
| `/library/switch` | POST | Switch active library |
| `/library/create` | POST | Create a library |
| `/library/<id>/rename` | POST | Rename a library |
| `/library/<id>/delete` | POST | Delete a library |

### Media and backup routes

| URL | Method | Purpose |
|-----|--------|---------|
| `/game/<id>/cover` | GET | Serve full cover media |
| `/game/<id>/cover/thumb` | GET | Serve cover thumbnail |
| `/backup` | POST | Create a manual backup |
| `/shutdown-backup` | POST | Create a backup before Electron quits |

When adding a route, validate user/library/game ownership before reading or
writing data, use `url_for()` for redirects, and add the route to this map if
it changes the project workflow.

---

## 6. Verification After Changes

Use the smallest checks that cover the changed surface, then escalate when
packaging or runtime behavior is affected.

### Source checks

```powershell
node --check main.js
node --check preload.js
node --check static\app.js
node --check static\i18n.js
.venv\Scripts\python.exe -m py_compile app.py scripts\build_backend.py
```

### Backend checks

- Exercise affected routes with Flask's test client.
- Cover user creation, game CRUD, session CRUD, media, library scoping, and
  backup behavior when those areas change.
- Test both an empty library and a populated library.
- Confirm invalid IDs and malformed form values produce explicit errors rather
  than foreign-key or server errors.

### Electron and packaging checks

```powershell
npm.cmd run build:backend
npm.cmd run build
```

For Electron-facing changes, manually verify startup, user creation, dashboard
navigation, adding/editing a game, cover display, session logging, statistics,
activity, library switching, theme/language toggles, window controls, and quit
backup behavior. For packaged changes, launch the generated
`dist\Ludarium 0.1.0.exe` and verify that data persists after restarting.

Do not claim that a GUI or packaging change is verified from syntax checks
alone. If the renderer is blank, inspect the Electron/Flask logs and verify
the local URL, renderer load events, and backend process before changing UI
code.

---

## 7. File and Module Conventions

| Path | Purpose |
|------|---------|
| `main.js` | Electron main process and backend lifecycle |
| `preload.js` | Sandboxed Electron window-control bridge |
| `package.json` | Node manifest and electron-builder configuration |
| `app.py` | Entire Flask application, schema, routes, and helpers |
| `requirements.txt` | Python runtime/build dependencies |
| `scripts/build_backend.py` | PyInstaller backend build helper |
| `run-ludarium.bat` | Windows development launcher |
| `Ludarium.vbs` | Silent Windows launcher using `npm start` |
| `static/style.css` | Layout, components, themes, and responsive design |
| `static/app.js` | Modals, theme, window controls, date defaults, shutdown |
| `static/i18n.js` | English/Spanish translation runtime |
| `static/splash.html` | Electron loading screen |
| `static/logo.svg`, `static/logo.png`, `static/logo.ico` | App branding and packaging assets |
| `templates/base.html` | Shared application shell |
| `templates/` | Server-rendered page templates |
| `.github/copilot-instructions.md` | Project-wide agent directives |

Keep changes focused and follow existing naming, formatting, helper, and
localisation patterns. Do not introduce a framework, ORM, bundler, or
dependency when the existing stack already solves the problem.

---

## 8. Commit Messages and Git Workflow

Every response that modifies code or files **must** end with a suggested commit
message inside a fenced code block. This applies to documentation, styles,
configuration, tests, fixes, and one-line changes.

Do not create or amend a commit unless the user explicitly asks for it. Keep
unrelated worktree changes intact. When commit preparation is requested, stage
only intentional repository files; never stage `data\`, `build\`, `dist\`,
`.venv\`, `node_modules\`, caches, databases, or user media.

### Format

```text
type(scope): lowercase imperative summary

* bullet describing a specific change
* another bullet
```

### Rules

| Element | Rule |
|---------|------|
| Type | `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, or another clear conventional type |
| Scope | Optional, for example `feat(sessions):` or `fix(packaging):` |
| Subject | Lowercase after the colon, imperative mood, no trailing period |
| Separator | Always leave one blank line between subject and body |
| Body | Use `*` bullets, one line per bullet, no trailing periods |
| Identifiers | Put routes, functions, files, and constants in backticks |
| Renames | Use `→` when describing a rename or move |

Example:

```text
feat(sessions): add session progress tracking

* store before and after progress values in `sessions`
* mark games completed when progress reaches 100 percent
* expose progress fields in the session form and detail history
* verify completion behavior with a Flask integration check
```

Before a requested commit, review `git status --short`, inspect the relevant
diff, run the smallest applicable validation, and ensure generated artifacts
remain ignored.

---

## 9. Versioning and Release Workflow

The application version is duplicated intentionally in:

| File | Field |
|------|-------|
| `app.py` | `APP_VERSION = "x.y.z"` |
| `package.json` | `"version": "x.y.z"` |

Keep both values synchronized whenever a release or explicit version bump is
requested. The repository does not currently contain a `CHANGELOG.md`; do not
invent a release entry for an ordinary change. If a changelog is introduced,
use a Keep a Changelog-style `## [Unreleased]` section and update it only when
the user asks for release/versioning work.

---

## 10. Change Checklist

Before finishing a change, confirm:

- [ ] The relevant backend, template, CSS, and i18n surfaces are wired
  consistently.
- [ ] User and active-library scoping is preserved.
- [ ] Existing SQLite databases remain usable.
- [ ] Errors are explicit and actionable.
- [ ] New user-facing text exists in English and Spanish.
- [ ] Generated data and build artifacts are not tracked.
- [ ] Targeted syntax/runtime checks pass.
- [ ] Packaging is rebuilt when Electron, PyInstaller, resources, or build
  configuration changes.
- [ ] The final response includes a conventional suggested commit message.
