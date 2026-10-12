"""Ludarium - a local Flask app for tracking games and play sessions."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    has_request_context,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)


# ---------------------------------------------------------------------------
# Paths and application constants
# ---------------------------------------------------------------------------

SOURCE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))
BASE_DIR = SOURCE_DIR
DATA_DIR = Path(
    os.environ.get("LUDARIUM_DATA_DIR", str(BASE_DIR / "data"))
).resolve()
BACKUP_DIR = DATA_DIR / "backups"
USERS_FILE = DATA_DIR / "users.json"
DB_PATH = DATA_DIR / "ludarium.db"
APP_VERSION = "0.1.0"
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

STATUS_LABELS = {
    "wishlist": "Wishlist",
    "backlog": "Backlog",
    "playing": "Playing",
    "completed": "Completed",
    "abandoned": "Abandoned",
    "replaying": "Replaying",
}
STATUS_VALUES = tuple(STATUS_LABELS)
GAME_TYPE_VALUES = (
    "base_game",
    "expansion",
    "remake",
    "remaster",
    "demo",
    "collection",
)
OWNERSHIP_VALUES = (
    "owned",
    "subscription",
    "borrowed",
    "free_to_play",
    "cloud",
    "not_owned",
)
SESSION_TYPE_VALUES = (
    "regular",
    "multiplayer",
    "replay",
    "completion",
    "achievement",
)
MODE_VALUES = ("solo", "local_coop", "online", "competitive", "mixed")
PLAYTHROUGH_STATUS_LABELS = {
    "active": "Active",
    "completed": "Completed",
    "abandoned": "Abandoned",
}
PLAYTHROUGH_STATUS_VALUES = tuple(PLAYTHROUGH_STATUS_LABELS)
RATING_DIMENSIONS = (
    ("gameplay", "Gameplay"),
    ("story", "Story"),
    ("visuals", "Visuals"),
    ("audio", "Audio"),
    ("performance", "Performance"),
    ("accessibility", "Accessibility"),
    ("replayability", "Replayability"),
)

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.secret_key = os.environ.get("LUDARIUM_SECRET", "ludarium-local-dev-key")


# ---------------------------------------------------------------------------
# User and storage helpers
# ---------------------------------------------------------------------------

def _sanitize_username(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().strip()) or "default"


def _load_users() -> dict[str, Any]:
    if USERS_FILE.exists():
        try:
            value = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict) and isinstance(value.get("users"), list):
            return value
    return {"users": [], "last_user": ""}


def _save_users(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _find_user(username: str, users_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not username:
        return None
    users_data = users_data or _load_users()
    for user in users_data.get("users", []):
        if isinstance(user, dict) and user.get("name") == username:
            return user
    return None


def _user_db_path(username: str) -> Path:
    return DATA_DIR / f"{_sanitize_username(username)}.db"


def _user_backup_dir(username: str) -> Path:
    user = _find_user(username)
    if user and user.get("backup_dir"):
        candidate = Path(str(user["backup_dir"]))
        if candidate.is_absolute():
            return candidate
    return BACKUP_DIR / _sanitize_username(username)


def _get_valid_current_user(users_data: dict[str, Any] | None = None) -> str:
    if not has_request_context():
        return ""
    users_data = users_data or _load_users()
    username = request.cookies.get("ludarium_user", "").strip()
    user = _find_user(username, users_data)
    if user is None:
        last_user = str(users_data.get("last_user", "")).strip()
        user = _find_user(last_user, users_data)
    return str(user["name"]) if user else ""


def _set_user_response(response: Response, username: str) -> Response:
    response.set_cookie(
        "ludarium_user",
        username,
        httponly=True,
        samesite="Lax",
        max_age=USER_COOKIE_MAX_AGE,
    )
    return response


def _set_library_response(response: Response, library_id: int | None) -> Response:
    if library_id is None:
        response.delete_cookie("ludarium_library")
    else:
        response.set_cookie("ludarium_library", str(library_id), samesite="Lax")
    return response


# ---------------------------------------------------------------------------
# Database schema and helpers
# ---------------------------------------------------------------------------

def _init_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS libraries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            original_title TEXT NOT NULL DEFAULT '',
            sort_title TEXT NOT NULL DEFAULT '',
            release_date TEXT NOT NULL DEFAULT '',
            release_year INTEGER,
            description TEXT NOT NULL DEFAULT '',
            game_type TEXT NOT NULL DEFAULT 'base_game',
            status TEXT NOT NULL DEFAULT 'backlog',
            content_rating TEXT NOT NULL DEFAULT '',
            modes TEXT NOT NULL DEFAULT '',
            genres TEXT NOT NULL DEFAULT '',
            subgenres TEXT NOT NULL DEFAULT '',
            themes TEXT NOT NULL DEFAULT '',
            developers TEXT NOT NULL DEFAULT '',
            publishers TEXT NOT NULL DEFAULT '',
            series TEXT NOT NULL DEFAULT '',
            series_position TEXT NOT NULL DEFAULT '',
            ownership TEXT NOT NULL DEFAULT 'not_owned',
            edition TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            estimated_minutes INTEGER,
            rating REAL,
            date_added TEXT NOT NULL DEFAULT '',
            start_date TEXT NOT NULL DEFAULT '',
            completion_date TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS platforms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS game_platforms (
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            platform_id INTEGER NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
            is_primary INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, platform_id)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS game_tags (
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (game_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS game_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'cover',
            blob BLOB NOT NULL,
            mime TEXT NOT NULL DEFAULT 'image/jpeg',
            thumb_blob BLOB,
            thumb_mime TEXT NOT NULL DEFAULT 'image/jpeg',
            content_hash TEXT NOT NULL DEFAULT '',
            is_primary INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS playthroughs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            run_number INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            started_date TEXT NOT NULL DEFAULT '',
            completed_date TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (game_id, run_number)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            dimension_key TEXT NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY (game_id, dimension_key)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            playthrough_id INTEGER REFERENCES playthroughs(id) ON DELETE SET NULL,
            session_date TEXT NOT NULL,
            start_time TEXT NOT NULL DEFAULT '',
            end_time TEXT NOT NULL DEFAULT '',
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            platform_id INTEGER REFERENCES platforms(id) ON DELETE SET NULL,
            session_type TEXT NOT NULL DEFAULT 'regular',
            mode TEXT NOT NULL DEFAULT 'solo',
            progress_before REAL,
            progress_after REAL,
            progress_percent REAL,
            chapter TEXT NOT NULL DEFAULT '',
            objective TEXT NOT NULL DEFAULT '',
            participants TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            achievements TEXT NOT NULL DEFAULT '',
            mood TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            changed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_games_library_status
            ON games(library_id, status);
        CREATE INDEX IF NOT EXISTS idx_sessions_game_date
            ON sessions(game_id, session_date);
        CREATE INDEX IF NOT EXISTS idx_playthroughs_game
            ON playthroughs(game_id, run_number);
        CREATE INDEX IF NOT EXISTS idx_sessions_date
            ON sessions(session_date);
        """
    )
    session_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "playthrough_id" not in session_columns:
        db.execute(
            """
            ALTER TABLE sessions
            ADD COLUMN playthrough_id INTEGER
            REFERENCES playthroughs(id) ON DELETE SET NULL
            """
        )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_playthrough_date
            ON sessions(playthrough_id, session_date)
        """
    )
    if db.execute("SELECT COUNT(*) FROM libraries").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO libraries (name, slug) VALUES (?, ?)",
            ("Games", "games"),
        )
    db.commit()


def _open_db(username: str) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(_user_db_path(username)), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    _init_schema(db)
    return db


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        username = _get_valid_current_user()
        if not username:
            raise RuntimeError("A valid Ludarium user is required.")
        g.db = _open_db(username)
    return g.db


@app.teardown_appcontext
def close_db(_exception: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _active_library(db: sqlite3.Connection) -> sqlite3.Row:
    libraries = db.execute(
        "SELECT * FROM libraries ORDER BY name COLLATE NOCASE"
    ).fetchall()
    if not libraries:
        raise RuntimeError("The database has no library.")
    requested = request.cookies.get("ludarium_library", "").strip()
    if requested.isdigit():
        for library in libraries:
            if library["id"] == int(requested):
                return library
    return libraries[0]


def _library_id(db: sqlite3.Connection) -> int:
    return int(_active_library(db)["id"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "item"


def _unique_slug(db: sqlite3.Connection, table: str, name: str, current_id: int | None = None) -> str:
    base = _slugify(name)
    slug = base
    index = 2
    while True:
        query = f"SELECT id FROM {table} WHERE slug = ?"
        params: list[Any] = [slug]
        if current_id is not None:
            query += " AND id != ?"
            params.append(current_id)
        if db.execute(query, params).fetchone() is None:
            return slug
        slug = f"{base}-{index}"
        index += 1


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Form and presentation helpers
# ---------------------------------------------------------------------------

def _clean(value: Any) -> str:
    return str(value or "").strip()


def _split_values(value: Any) -> list[str]:
    values = re.split(r"[;\n]+", _clean(value))
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        item = item.strip()
        key = item.casefold()
        if item and key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _join_values(values: list[str]) -> str:
    return "; ".join(values)


def _safe_int(value: Any, minimum: int | None = None, maximum: int | None = None) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        number = int(text)
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _safe_float(value: Any, minimum: float | None = None, maximum: float | None = None) -> float | None:
    text = _clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return round(number, 2)


def _normalise_date(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def _duration_label(seconds: int | float | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _duration_hms(seconds: int | float | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _process_cover(file_storage: Any) -> dict[str, Any] | None:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    raw = file_storage.read()
    if not raw or len(raw) > 15 * 1024 * 1024:
        raise ValueError("Cover images must be smaller than 15 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            image.thumbnail((480, 720))
            thumb_buffer = io.BytesIO()
            image.convert("RGB").save(thumb_buffer, format="JPEG", quality=88)
            thumb = thumb_buffer.getvalue()
            mime = str(Image.MIME.get(image.format, "image/jpeg"))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The cover must be a valid image.") from exc
    return {
        "blob": raw,
        "mime": mime,
        "thumb_blob": thumb,
        "thumb_mime": "image/jpeg",
        "content_hash": hashlib.sha256(raw).hexdigest(),
    }


def _game_form_values(form: Any) -> tuple[dict[str, Any], list[str], list[str], list[str], str | None]:
    title = _clean(form.get("title"))
    if not title:
        return {}, [], [], [], "A title is required."

    status = _clean(form.get("status")) or "backlog"
    if status not in STATUS_VALUES:
        return {}, [], [], [], "Choose a valid game status."
    game_type = _clean(form.get("game_type")) or "base_game"
    if game_type not in GAME_TYPE_VALUES:
        game_type = "base_game"
    ownership = _clean(form.get("ownership")) or "not_owned"
    if ownership not in OWNERSHIP_VALUES:
        ownership = "not_owned"

    release_date = _normalise_date(form.get("release_date"))
    release_year = _safe_int(form.get("release_year"), 1900, 2200)
    if release_date and release_year is None:
        release_year = int(release_date[:4])

    estimated_hours = _safe_float(form.get("estimated_hours"), 0, 100000)
    estimated_minutes = round(estimated_hours * 60) if estimated_hours is not None else None
    rating = _safe_float(form.get("rating"), 0, 10)
    data = {
        "title": title,
        "original_title": _clean(form.get("original_title")),
        "sort_title": _clean(form.get("sort_title")) or title.casefold(),
        "release_date": release_date,
        "release_year": release_year,
        "description": _clean(form.get("description")),
        "game_type": game_type,
        "status": status,
        "content_rating": _clean(form.get("content_rating")),
        "modes": _join_values(_split_values(form.get("modes"))),
        "genres": _join_values(_split_values(form.get("genres"))),
        "subgenres": _join_values(_split_values(form.get("subgenres"))),
        "themes": _join_values(_split_values(form.get("themes"))),
        "developers": _join_values(_split_values(form.get("developers"))),
        "publishers": _join_values(_split_values(form.get("publishers"))),
        "series": _clean(form.get("series")),
        "series_position": _clean(form.get("series_position")),
        "ownership": ownership,
        "edition": _clean(form.get("edition")),
        "region": _clean(form.get("region")),
        "source": _clean(form.get("source")),
        "estimated_minutes": estimated_minutes,
        "rating": rating,
        "start_date": _normalise_date(form.get("start_date")),
        "completion_date": _normalise_date(form.get("completion_date")),
        "notes": _clean(form.get("notes")),
    }
    platforms = _split_values(form.get("platforms"))
    tags = _split_values(form.get("tags"))
    return data, platforms, tags, [], None


def _save_named_relations(
    db: sqlite3.Connection,
    game_id: str,
    names: list[str],
    table: str,
    join_table: str,
) -> None:
    db.execute(f"DELETE FROM {join_table} WHERE game_id = ?", (game_id,))
    for position, name in enumerate(names):
        slug = _slugify(name)
        db.execute(
            f"INSERT OR IGNORE INTO {table} (name, slug) VALUES (?, ?)",
            (name, slug),
        )
        row = db.execute(f"SELECT id FROM {table} WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            continue
        if table == "platforms":
            db.execute(
                "INSERT OR REPLACE INTO game_platforms (game_id, platform_id, is_primary) VALUES (?, ?, ?)",
                (game_id, row["id"], 1 if position == 0 else 0),
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO game_tags (game_id, tag_id) VALUES (?, ?)",
                (game_id, row["id"]),
            )


def _game_platforms(db: sqlite3.Connection, game_id: str) -> list[str]:
    rows = db.execute(
        """
        SELECT p.name
        FROM game_platforms gp
        JOIN platforms p ON p.id = gp.platform_id
        WHERE gp.game_id = ?
        ORDER BY gp.is_primary DESC, p.name COLLATE NOCASE
        """,
        (game_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _game_tags(db: sqlite3.Connection, game_id: str) -> list[str]:
    rows = db.execute(
        """
        SELECT t.name
        FROM game_tags gt
        JOIN tags t ON t.id = gt.tag_id
        WHERE gt.game_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (game_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _game_form_data(db: sqlite3.Connection, game: sqlite3.Row) -> dict[str, Any]:
    data = dict(game)
    data["platforms"] = _join_values(_game_platforms(db, game["id"]))
    data["tags"] = _join_values(_game_tags(db, game["id"]))
    if data.get("estimated_minutes") is not None:
        data["estimated_hours"] = round(data["estimated_minutes"] / 60, 1)
    else:
        data["estimated_hours"] = ""
    return data


def _save_ratings(db: sqlite3.Connection, game_id: str, form: Any) -> None:
    db.execute("DELETE FROM ratings WHERE game_id = ?", (game_id,))
    for key, _label in RATING_DIMENSIONS:
        value = _safe_float(form.get(f"rating_{key}"), 0, 10)
        if value is not None:
            db.execute(
                "INSERT INTO ratings (game_id, dimension_key, value) VALUES (?, ?, ?)",
                (game_id, key, value),
            )


def _ratings_for_game(db: sqlite3.Connection, game_id: str) -> dict[str, float]:
    rows = db.execute(
        "SELECT dimension_key, value FROM ratings WHERE game_id = ?",
        (game_id,),
    ).fetchall()
    return {str(row["dimension_key"]): float(row["value"]) for row in rows}


def _save_media(db: sqlite3.Connection, game_id: str, media: dict[str, Any] | None) -> None:
    if not media:
        return
    db.execute(
        "UPDATE game_media SET is_primary = 0 WHERE game_id = ? AND kind = 'cover'",
        (game_id,),
    )
    db.execute(
        """
        INSERT INTO game_media
            (game_id, kind, blob, mime, thumb_blob, thumb_mime, content_hash, is_primary)
        VALUES (?, 'cover', ?, ?, ?, ?, ?, 1)
        """,
        (
            game_id,
            media["blob"],
            media["mime"],
            media["thumb_blob"],
            media["thumb_mime"],
            media["content_hash"],
        ),
    )


def _record_status(db: sqlite3.Connection, game_id: str, status: str, changed_at: str | None = None) -> None:
    timestamp = changed_at or datetime.now().isoformat(timespec="seconds")
    last = db.execute(
        "SELECT status FROM status_history WHERE game_id = ? ORDER BY id DESC LIMIT 1",
        (game_id,),
    ).fetchone()
    if last is None or last["status"] != status:
        db.execute(
            "INSERT INTO status_history (game_id, status, changed_at) VALUES (?, ?, ?)",
            (game_id, status, timestamp),
        )


def _primary_media(db: sqlite3.Connection, game_id: str) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT id, mime, thumb_mime, content_hash
        FROM game_media
        WHERE game_id = ? AND kind = 'cover'
        ORDER BY is_primary DESC, id DESC
        LIMIT 1
        """,
        (game_id,),
    ).fetchone()


def _backup_database(username: str) -> str | None:
    source_path = _user_db_path(username)
    if not source_path.exists():
        return None
    target_dir = _user_backup_dir(username)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    target = target_dir / f"ludarium_{stamp}.db"
    source = sqlite3.connect(str(source_path))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backups = sorted(target_dir.glob("ludarium_*.db"), key=lambda item: item.stat().st_mtime)
    for old_backup in backups[:-5]:
        old_backup.unlink(missing_ok=True)
    return str(target)


def _current_user_or_abort() -> str:
    username = _get_valid_current_user()
    if not username:
        abort(403)
    return username


def _game_in_library(db: sqlite3.Connection, game_id: str, library_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM games WHERE id = ? AND library_id = ?",
        (game_id, library_id),
    ).fetchone()


def _playthrough_for_game(
    db: sqlite3.Connection,
    playthrough_id: int | None,
    game_id: str,
) -> sqlite3.Row | None:
    if playthrough_id is None:
        return None
    return db.execute(
        """
        SELECT p.*
        FROM playthroughs p
        WHERE p.id = ? AND p.game_id = ?
        """,
        (playthrough_id, game_id),
    ).fetchone()


def _playthrough_for_library(
    db: sqlite3.Connection,
    playthrough_id: int | None,
    library_id: int,
) -> sqlite3.Row | None:
    if playthrough_id is None:
        return None
    return db.execute(
        """
        SELECT p.*, g.title, g.id AS game_id
        FROM playthroughs p
        JOIN games g ON g.id = p.game_id
        WHERE p.id = ? AND g.library_id = ?
        """,
        (playthrough_id, library_id),
    ).fetchone()


def _playthroughs_for_game(
    db: sqlite3.Connection,
    game_id: str,
) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT p.*,
               COUNT(s.id) AS session_count,
               COALESCE(SUM(s.duration_seconds), 0) AS seconds,
               MIN(s.session_date) AS first_session,
               MAX(s.session_date) AS last_session
        FROM playthroughs p
        LEFT JOIN sessions s ON s.playthrough_id = p.id
        WHERE p.game_id = ?
        GROUP BY p.id
        ORDER BY p.run_number
        """,
        (game_id,),
    ).fetchall()


def _playthroughs_for_library(
    db: sqlite3.Connection,
    library_id: int,
) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT p.id, p.game_id, p.run_number, p.name, p.status,
               g.title
        FROM playthroughs p
        JOIN games g ON g.id = p.game_id
        WHERE g.library_id = ?
        ORDER BY g.sort_title COLLATE NOCASE, p.run_number
        """,
        (library_id,),
    ).fetchall()


def _next_playthrough_number(db: sqlite3.Connection, game_id: str) -> int:
    value = db.execute(
        "SELECT COALESCE(MAX(run_number), 0) + 1 FROM playthroughs WHERE game_id = ?",
        (game_id,),
    ).fetchone()[0]
    return int(value)


def _parse_playthrough_values(
    form: Any,
    default_status: str = "active",
) -> tuple[dict[str, str], str | None]:
    status = _clean(form.get("status")) or default_status
    if status not in PLAYTHROUGH_STATUS_VALUES:
        return {}, "Choose a valid playthrough status."
    started_date = _normalise_date(form.get("started_date"))
    completed_date = _normalise_date(form.get("completed_date"))
    if started_date and completed_date and completed_date < started_date:
        return {}, "The completion date must be on or after the start date."
    return {
        "name": _clean(form.get("name")),
        "status": status,
        "started_date": started_date,
        "completed_date": completed_date,
        "notes": _clean(form.get("notes")),
    }, None


def _parse_session_values(
    db: sqlite3.Connection,
    form: Any,
    session_date: str,
    duration_minutes: float | None,
    game_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    duration_seconds = round((duration_minutes or 0) * 60)
    session_type = _clean(form.get("session_type")) or "regular"
    if session_type not in SESSION_TYPE_VALUES:
        session_type = "regular"
    mode = _clean(form.get("mode")) or "solo"
    if mode not in MODE_VALUES:
        mode = "solo"
    progress_before = _safe_float(form.get("progress_before"), 0, 100)
    progress_after = _safe_float(form.get("progress_after"), 0, 100)
    progress_percent = _safe_float(form.get("progress_percent"), 0, 100)
    if progress_percent is None and progress_after is not None:
        progress_percent = progress_after
    platform_id = _safe_int(form.get("platform_id"), 1)
    if platform_id is not None and db.execute(
        "SELECT 1 FROM platforms WHERE id = ?", (platform_id,)
    ).fetchone() is None:
        return {}, "Choose a valid platform for the session."
    playthrough_id = _safe_int(form.get("playthrough_id"), 1)
    if playthrough_id is not None and (
        not game_id or _playthrough_for_game(db, playthrough_id, game_id) is None
    ):
        return {}, "Choose a valid playthrough for the selected game."
    return {
        "session_date": session_date,
        "start_time": _clean(form.get("start_time")),
        "end_time": _clean(form.get("end_time")),
        "duration_seconds": duration_seconds,
        "platform_id": platform_id,
        "playthrough_id": playthrough_id,
        "session_type": session_type,
        "mode": mode,
        "progress_before": progress_before,
        "progress_after": progress_after,
        "progress_percent": progress_percent,
        "chapter": _clean(form.get("chapter")),
        "objective": _clean(form.get("objective")),
        "participants": _clean(form.get("participants")),
        "location": _clean(form.get("location")),
        "achievements": _clean(form.get("achievements")),
        "mood": _clean(form.get("mood")),
        "notes": _clean(form.get("notes")),
    }, None


def _parse_session_form(
    db: sqlite3.Connection,
    form: Any,
    game_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    session_date = _normalise_date(form.get("session_date"))
    if not session_date:
        return {}, "A valid session date is required."
    duration_minutes = _safe_float(form.get("duration_minutes"), 0, 100000)
    return _parse_session_values(db, form, session_date, duration_minutes, game_id)


def _parse_session_entries(
    db: sqlite3.Connection,
    form: Any,
    game_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    range_fields = (
        form.get("range_start_date"),
        form.get("range_end_date"),
        form.get("range_duration_minutes"),
    )
    if not any(_clean(value) for value in range_fields):
        values, error = _parse_session_form(db, form, game_id)
        return ([values] if not error else []), error

    start_date = _normalise_date(form.get("range_start_date"))
    end_date = _normalise_date(form.get("range_end_date"))
    if not start_date or not end_date:
        return [], "Enter a valid start and end date for the playing range."
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        return [], "The playing range end date must be on or after its start date."

    total_minutes = _safe_float(form.get("range_duration_minutes"), 0, 100000)
    if total_minutes is None or total_minutes <= 0:
        return [], "Enter a total play time greater than 0 minutes."

    template, error = _parse_session_values(db, form, start_date, 0, game_id)
    if error:
        return [], error

    day_count = (end - start).days + 1
    total_seconds = round(total_minutes * 60)
    daily_seconds, remainder = divmod(total_seconds, day_count)
    entries: list[dict[str, Any]] = []
    for offset in range(day_count):
        values = dict(template)
        values["session_date"] = (start + timedelta(days=offset)).isoformat()
        values["duration_seconds"] = daily_seconds + (1 if offset < remainder else 0)
        entries.append(values)
    return entries, None


def _list_games(db: sqlite3.Connection, library_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT g.*,
               COALESCE(GROUP_CONCAT(DISTINCT p.name), '') AS platform_names,
               (SELECT id FROM game_media m
                WHERE m.game_id = g.id AND m.kind = 'cover'
                ORDER BY m.is_primary DESC, m.id DESC LIMIT 1) AS media_id
        FROM games g
        LEFT JOIN game_platforms gp ON gp.game_id = g.id
        LEFT JOIN platforms p ON p.id = gp.platform_id
        WHERE g.library_id = ?
        GROUP BY g.id
        ORDER BY g.sort_title COLLATE NOCASE
        """,
        (library_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _format_game_for_template(db: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["platform_list"] = (
        row.get("platform_names", "").split(",") if row.get("platform_names") else []
    )
    row["status_label"] = STATUS_LABELS.get(row.get("status", ""), row.get("status", ""))
    row["rating_label"] = f"{row['rating']:.1f}" if row.get("rating") is not None else ""
    return row


# ---------------------------------------------------------------------------
# Request lifecycle and shared template globals
# ---------------------------------------------------------------------------

@app.before_request
def require_user() -> Response | None:
    if request.endpoint in {"static", "user_select", "user_create", "user_switch"}:
        return None
    username = _get_valid_current_user()
    if not username:
        return redirect(url_for("user_select"))
    if request.cookies.get("ludarium_user", "").strip() != username:
        response = make_response(redirect(request.url))
        return _set_user_response(response, username)
    return None


@app.context_processor
def inject_globals() -> dict[str, Any]:
    username = _get_valid_current_user()
    if not username:
        return {
            "current_user": "",
            "all_libraries": [],
            "current_library": None,
            "app_version": APP_VERSION,
            "now": datetime.now(),
            "status_labels": STATUS_LABELS,
            "playthrough_status_labels": PLAYTHROUGH_STATUS_LABELS,
        }
    db = get_db()
    libraries = db.execute(
        "SELECT * FROM libraries ORDER BY name COLLATE NOCASE"
    ).fetchall()
    current_library = _active_library(db)
    return {
        "current_user": username,
        "all_libraries": libraries,
        "current_library": current_library,
        "app_version": APP_VERSION,
        "now": datetime.now(),
        "status_labels": STATUS_LABELS,
        "playthrough_status_labels": PLAYTHROUGH_STATUS_LABELS,
        "db_location": str(_user_db_path(username)),
        "backup_location": str(_user_backup_dir(username)),
    }


app.jinja_env.filters["duration"] = _duration_label
app.jinja_env.filters["duration_hms"] = _duration_hms


# ---------------------------------------------------------------------------
# User and library routes
# ---------------------------------------------------------------------------

@app.route("/users")
def user_select() -> str:
    return render_template("users.html", users=_load_users().get("users", []))


@app.route("/users/create", methods=["POST"])
def user_create() -> Response:
    name = _clean(request.form.get("name"))
    if not name:
        flash("A user name is required.", "error")
        return redirect(url_for("user_select"))
    users_data = _load_users()
    if _find_user(name, users_data):
        flash("That user already exists.", "error")
        return redirect(url_for("user_select"))
    user = {"name": name, "backup_dir": ""}
    users_data.setdefault("users", []).append(user)
    users_data["last_user"] = name
    _save_users(users_data)
    db = _open_db(name)
    db.close()
    return _set_user_response(make_response(redirect(url_for("dashboard"))), name)


@app.route("/users/switch", methods=["POST"])
def user_switch() -> Response:
    username = _clean(request.form.get("username"))
    if not _find_user(username):
        flash("That user could not be found.", "error")
        return redirect(url_for("user_select"))
    users_data = _load_users()
    users_data["last_user"] = username
    _save_users(users_data)
    response = make_response(redirect(url_for("dashboard")))
    response = _set_user_response(response, username)
    response = _set_library_response(response, None)
    return response


@app.route("/library/switch", methods=["POST"])
def switch_library() -> Response:
    db = get_db()
    library_id = _safe_int(request.form.get("library_id"), 1)
    if library_id is None or db.execute(
        "SELECT 1 FROM libraries WHERE id = ?", (library_id,)
    ).fetchone() is None:
        flash("That library could not be found.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    response = make_response(redirect(request.referrer or url_for("dashboard")))
    return _set_library_response(response, library_id)


@app.route("/library/create", methods=["POST"])
def create_library() -> Response:
    db = get_db()
    name = _clean(request.form.get("name"))
    if not name:
        flash("A library name is required.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    try:
        db.execute(
            "INSERT INTO libraries (name, slug) VALUES (?, ?)",
            (name, _unique_slug(db, "libraries", name)),
        )
        db.commit()
        flash(f"Library '{name}' created.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("A library with that name already exists.", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/library/<int:library_id>/rename", methods=["POST"])
def rename_library(library_id: int) -> Response:
    db = get_db()
    name = _clean(request.form.get("name"))
    if not name:
        flash("A library name is required.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    try:
        db.execute(
            "UPDATE libraries SET name = ?, slug = ? WHERE id = ?",
            (name, _unique_slug(db, "libraries", name, library_id), library_id),
        )
        db.commit()
        flash("Library renamed.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("A library with that name already exists.", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/library/<int:library_id>/delete", methods=["POST"])
def delete_library(library_id: int) -> Response:
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM libraries").fetchone()[0]
    if count <= 1:
        flash("The last library cannot be deleted.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    db.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
    db.commit()
    flash("Library deleted.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Dashboard and catalog
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard() -> str:
    db = get_db()
    library_id = _library_id(db)
    total_games = db.execute(
        "SELECT COUNT(*) FROM games WHERE library_id = ?", (library_id,)
    ).fetchone()[0]
    status_counts = {
        row["status"]: row["count"]
        for row in db.execute(
            "SELECT status, COUNT(*) AS count FROM games WHERE library_id = ? GROUP BY status",
            (library_id,),
        ).fetchall()
    }
    totals = db.execute(
        """
        SELECT COUNT(s.id) AS sessions, COALESCE(SUM(s.duration_seconds), 0) AS seconds
        FROM sessions s
        JOIN games g ON g.id = s.game_id
        WHERE g.library_id = ?
        """,
        (library_id,),
    ).fetchone()
    playing = db.execute(
        """
        SELECT g.*,
               COALESCE(SUM(s.duration_seconds), 0) AS played_seconds,
               MAX(s.session_date) AS last_session,
               (SELECT id FROM game_media m WHERE m.game_id = g.id
                ORDER BY m.is_primary DESC, m.id DESC LIMIT 1) AS media_id
        FROM games g
        LEFT JOIN sessions s ON s.game_id = g.id
        WHERE g.library_id = ? AND g.status IN ('playing', 'replaying')
        GROUP BY g.id
        ORDER BY last_session DESC, g.sort_title COLLATE NOCASE
        LIMIT 8
        """,
        (library_id,),
    ).fetchall()
    recent_sessions = db.execute(
        """
        SELECT s.*, g.title, g.id AS game_id, p.name AS platform_name,
               pt.run_number, pt.name AS playthrough_name
        FROM sessions s
        JOIN games g ON g.id = s.game_id
        LEFT JOIN platforms p ON p.id = s.platform_id
        LEFT JOIN playthroughs pt ON pt.id = s.playthrough_id
        WHERE g.library_id = ?
        ORDER BY s.session_date DESC, s.id DESC
        LIMIT 8
        """,
        (library_id,),
    ).fetchall()
    latest_games = db.execute(
        """
        SELECT g.*,
               (SELECT id FROM game_media m WHERE m.game_id = g.id
                ORDER BY m.is_primary DESC, m.id DESC LIMIT 1) AS media_id
        FROM games g
        WHERE g.library_id = ?
        ORDER BY g.date_added DESC, g.sort_title COLLATE NOCASE
        LIMIT 8
        """,
        (library_id,),
    ).fetchall()
    return render_template(
        "dashboard.html",
        total_games=total_games,
        status_counts=status_counts,
        totals=totals,
        playing=playing,
        recent_sessions=recent_sessions,
        latest_games=latest_games,
    )


@app.route("/library")
def library() -> str:
    db = get_db()
    library_id = _library_id(db)
    query = _clean(request.args.get("q"))
    status_filter = _clean(request.args.get("status"))
    platform_filter = _safe_int(request.args.get("platform"), 1)
    genre_filter = _clean(request.args.get("genre"))
    sort = _clean(request.args.get("sort")) or "title"
    order = "DESC" if _clean(request.args.get("order")) == "desc" else "ASC"
    view = _clean(request.args.get("view")) or "card"

    clauses = ["g.library_id = ?"]
    params: list[Any] = [library_id]
    if query:
        clauses.append(
            "(g.title LIKE ? OR g.original_title LIKE ? OR g.developers LIKE ? OR g.publishers LIKE ?)"
        )
        wildcard = f"%{query}%"
        params.extend([wildcard] * 4)
    if status_filter in STATUS_VALUES:
        clauses.append("g.status = ?")
        params.append(status_filter)
    if platform_filter:
        clauses.append(
            "EXISTS (SELECT 1 FROM game_platforms fgp WHERE fgp.game_id = g.id AND fgp.platform_id = ?)"
        )
        params.append(platform_filter)
    if genre_filter:
        clauses.append("g.genres LIKE ?")
        params.append(f"%{genre_filter}%")

    sort_columns = {
        "title": "g.sort_title",
        "date_added": "g.date_added",
        "release_year": "g.release_year",
        "rating": "g.rating",
        "status": "g.status",
    }
    sort_column = sort_columns.get(sort, "g.sort_title")
    rows = db.execute(
        f"""
        SELECT g.*,
               COALESCE(GROUP_CONCAT(DISTINCT p.name), '') AS platform_names,
               (SELECT id FROM game_media m WHERE m.game_id = g.id
                ORDER BY m.is_primary DESC, m.id DESC LIMIT 1) AS media_id
        FROM games g
        LEFT JOIN game_platforms gp ON gp.game_id = g.id
        LEFT JOIN platforms p ON p.id = gp.platform_id
        WHERE {' AND '.join(clauses)}
        GROUP BY g.id
        ORDER BY {sort_column} {order}, g.sort_title COLLATE NOCASE
        """,
        params,
    ).fetchall()
    games = [_format_game_for_template(db, dict(row)) for row in rows]
    platforms = db.execute(
        """
        SELECT p.id, p.name, COUNT(g.id) AS game_count
        FROM platforms p
        LEFT JOIN game_platforms gp ON gp.platform_id = p.id
        LEFT JOIN games g ON g.id = gp.game_id AND g.library_id = ?
        GROUP BY p.id
        ORDER BY p.name COLLATE NOCASE
        """,
        (library_id,),
    ).fetchall()
    genres = sorted(
        {
            genre
            for game in _list_games(db, library_id)
            for genre in _split_values(game.get("genres"))
        },
        key=str.casefold,
    )
    return render_template(
        "library.html",
        games=games,
        platforms=platforms,
        genres=genres,
        query=query,
        status_filter=status_filter,
        platform_filter=platform_filter,
        genre_filter=genre_filter,
        sort=sort,
        order=order.lower(),
        view=view,
    )


# ---------------------------------------------------------------------------
# Game CRUD and media
# ---------------------------------------------------------------------------

def _render_game_form(
    template: str,
    *,
    game_data: dict[str, Any],
    ratings: dict[str, float],
    errors: list[str] | None = None,
) -> str:
    db = get_db()
    library_id = _library_id(db)
    platform_names = [
        row["name"]
        for row in db.execute("SELECT name FROM platforms ORDER BY name COLLATE NOCASE").fetchall()
    ]
    return render_template(
        template,
        game=game_data,
        ratings=ratings,
        errors=errors or [],
        platform_names=platform_names,
        statuses=STATUS_LABELS,
        game_types=GAME_TYPE_VALUES,
        ownership_values=OWNERSHIP_VALUES,
        rating_dimensions=RATING_DIMENSIONS,
        current_library_id=library_id,
    )


@app.route("/game/new", methods=["GET", "POST"])
def new_game() -> str | Response:
    db = get_db()
    if request.method == "GET":
        return _render_game_form("game_form.html", game_data={}, ratings={})
    data, platforms, tags, _unused, error = _game_form_values(request.form)
    if error:
        return _render_game_form(
            "game_form.html",
            game_data=request.form.to_dict(flat=True),
            ratings={},
            errors=[error],
        )
    try:
        media = _process_cover(request.files.get("cover"))
    except ValueError as exc:
        return _render_game_form(
            "game_form.html",
            game_data=request.form.to_dict(flat=True),
            ratings={},
            errors=[str(exc)],
        )
    game_id = uuid.uuid4().hex
    now = date.today().isoformat()
    data["date_added"] = now
    data["library_id"] = _library_id(db)
    db.execute(
        """
        INSERT INTO games (
            id, title, original_title, sort_title, release_date, release_year,
            description, game_type, status, content_rating, modes, genres,
            subgenres, themes, developers, publishers, series, series_position,
            ownership, edition, region, source, estimated_minutes, rating,
            date_added, start_date, completion_date, notes, library_id
        ) VALUES (
            :id, :title, :original_title, :sort_title, :release_date, :release_year,
            :description, :game_type, :status, :content_rating, :modes, :genres,
            :subgenres, :themes, :developers, :publishers, :series, :series_position,
            :ownership, :edition, :region, :source, :estimated_minutes, :rating,
            :date_added, :start_date, :completion_date, :notes, :library_id
        )
        """,
        {"id": game_id, **data},
    )
    _save_named_relations(db, game_id, platforms, "platforms", "game_platforms")
    _save_named_relations(db, game_id, tags, "tags", "game_tags")
    _save_ratings(db, game_id, request.form)
    _record_status(db, game_id, data["status"], now)
    _save_media(db, game_id, media)
    db.commit()
    flash("Game added to the library.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/game/<game_id>/playthrough/new", methods=["POST"])
def new_playthrough(game_id: str) -> Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    values, error = _parse_playthrough_values(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("game_detail", game_id=game_id))
    run_number = _next_playthrough_number(db, game_id)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO playthroughs (
            game_id, run_number, name, status, started_date, completed_date,
            notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            run_number,
            values["name"],
            values["status"],
            values["started_date"],
            values["completed_date"],
            values["notes"],
            now,
            now,
        ),
    )
    db.commit()
    flash("Playthrough created.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/playthrough/<int:playthrough_id>/edit", methods=["GET", "POST"])
def edit_playthrough(playthrough_id: int) -> str | Response:
    db = get_db()
    playthrough = db.execute(
        """
        SELECT p.*, g.title, g.id AS game_id
        FROM playthroughs p
        JOIN games g ON g.id = p.game_id
        WHERE p.id = ? AND g.library_id = ?
        """,
        (playthrough_id, _library_id(db)),
    ).fetchone()
    if playthrough is None:
        abort(404)
    if request.method == "GET":
        return render_template(
            "playthrough_form.html",
            playthrough=playthrough,
            playthrough_statuses=PLAYTHROUGH_STATUS_VALUES,
        )
    values, error = _parse_playthrough_values(
        request.form,
        default_status=playthrough["status"],
    )
    if error:
        flash(error, "error")
        return redirect(url_for("edit_playthrough", playthrough_id=playthrough_id))
    db.execute(
        """
        UPDATE playthroughs
        SET name = ?, status = ?, started_date = ?, completed_date = ?,
            notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            values["name"],
            values["status"],
            values["started_date"],
            values["completed_date"],
            values["notes"],
            datetime.now().isoformat(timespec="seconds"),
            playthrough_id,
        ),
    )
    db.commit()
    flash("Playthrough updated.", "success")
    return redirect(url_for("game_detail", game_id=playthrough["game_id"]))


@app.route("/game/<game_id>/playthrough/assign-unassigned", methods=["POST"])
def assign_unassigned_sessions(game_id: str) -> Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    playthrough_id = _safe_int(request.form.get("playthrough_id"), 1)
    if playthrough_id is None or _playthrough_for_game(
        db, playthrough_id, game_id
    ) is None:
        flash("Choose a valid playthrough for the game.", "error")
        return redirect(url_for("game_detail", game_id=game_id))
    result = db.execute(
        """
        UPDATE sessions
        SET playthrough_id = ?, updated_at = ?
        WHERE game_id = ? AND playthrough_id IS NULL
        """,
        (
            playthrough_id,
            datetime.now().isoformat(timespec="seconds"),
            game_id,
        ),
    )
    db.commit()
    if result.rowcount:
        flash(f"Assigned {result.rowcount} sessions to the playthrough.", "success")
    else:
        flash("There are no unassigned sessions for this game.", "error")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/game/<game_id>")
def game_detail(game_id: str) -> str:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    sessions = db.execute(
        """
        SELECT s.*, p.name AS platform_name,
               pt.run_number, pt.name AS playthrough_name
        FROM sessions s
        LEFT JOIN platforms p ON p.id = s.platform_id
        LEFT JOIN playthroughs pt ON pt.id = s.playthrough_id
        WHERE s.game_id = ?
        ORDER BY s.session_date DESC, s.id DESC
        """,
        (game_id,),
    ).fetchall()
    playthroughs = _playthroughs_for_game(db, game_id)
    summary = db.execute(
        """
        SELECT COUNT(*) AS session_count, COALESCE(SUM(duration_seconds), 0) AS seconds,
               MAX(session_date) AS last_session
        FROM sessions WHERE game_id = ?
        """,
        (game_id,),
    ).fetchone()
    last_used_session = db.execute(
        """
        SELECT session_date, platform_id, progress_percent, session_type, mode,
               playthrough_id
        FROM sessions
        WHERE game_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (game_id,),
    ).fetchone()
    return render_template(
        "game_detail.html",
        game=game,
        platforms=_game_platforms(db, game_id),
        tags=_game_tags(db, game_id),
        ratings=_ratings_for_game(db, game_id),
        rating_dimensions=RATING_DIMENSIONS,
        media=_primary_media(db, game_id),
        sessions=sessions,
        playthroughs=playthroughs,
        unassigned_sessions=[row for row in sessions if row["playthrough_id"] is None],
        summary=summary,
        last_used_session=last_used_session,
        session_platforms=db.execute(
            "SELECT id, name FROM platforms ORDER BY name COLLATE NOCASE"
        ).fetchall(),
        session_types=SESSION_TYPE_VALUES,
        mode_values=MODE_VALUES,
    )


@app.route("/game/<game_id>/edit", methods=["GET", "POST"])
def edit_game(game_id: str) -> str | Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    if request.method == "GET":
        return _render_game_form(
            "game_form.html",
            game_data=_game_form_data(db, game),
            ratings=_ratings_for_game(db, game_id),
        )
    data, platforms, tags, _unused, error = _game_form_values(request.form)
    if error:
        return _render_game_form(
            "game_form.html",
            game_data=request.form.to_dict(flat=True),
            ratings=_ratings_for_game(db, game_id),
            errors=[error],
        )
    try:
        media = _process_cover(request.files.get("cover"))
    except ValueError as exc:
        return _render_game_form(
            "game_form.html",
            game_data=request.form.to_dict(flat=True),
            ratings=_ratings_for_game(db, game_id),
            errors=[str(exc)],
        )
    data["id"] = game_id
    db.execute(
        """
        UPDATE games SET
            title = :title, original_title = :original_title, sort_title = :sort_title,
            release_date = :release_date, release_year = :release_year,
            description = :description, game_type = :game_type, status = :status,
            content_rating = :content_rating, modes = :modes, genres = :genres,
            subgenres = :subgenres, themes = :themes, developers = :developers,
            publishers = :publishers, series = :series, series_position = :series_position,
            ownership = :ownership, edition = :edition, region = :region, source = :source,
            estimated_minutes = :estimated_minutes, rating = :rating,
            start_date = :start_date, completion_date = :completion_date, notes = :notes
        WHERE id = :id
        """,
        data,
    )
    _save_named_relations(db, game_id, platforms, "platforms", "game_platforms")
    _save_named_relations(db, game_id, tags, "tags", "game_tags")
    _save_ratings(db, game_id, request.form)
    _record_status(db, game_id, data["status"])
    _save_media(db, game_id, media)
    db.commit()
    flash("Game updated.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/game/<game_id>/delete", methods=["POST"])
def delete_game(game_id: str) -> Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    db.execute("DELETE FROM games WHERE id = ?", (game_id,))
    db.commit()
    flash("Game removed from the library.", "success")
    return redirect(url_for("library"))


@app.route("/game/<game_id>/cover")
def game_cover(game_id: str) -> Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    media = db.execute(
        """
        SELECT blob, mime FROM game_media
        WHERE game_id = ? AND kind = 'cover'
        ORDER BY is_primary DESC, id DESC LIMIT 1
        """,
        (game_id,),
    ).fetchone()
    if media is None:
        abort(404)
    return Response(media["blob"], mimetype=media["mime"])


@app.route("/game/<game_id>/cover/thumb")
def game_cover_thumb(game_id: str) -> Response:
    db = get_db()
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        abort(404)
    media = db.execute(
        """
        SELECT thumb_blob, thumb_mime FROM game_media
        WHERE game_id = ? AND kind = 'cover'
        ORDER BY is_primary DESC, id DESC LIMIT 1
        """,
        (game_id,),
    ).fetchone()
    if media is None or media["thumb_blob"] is None:
        abort(404)
    return Response(media["thumb_blob"], mimetype=media["thumb_mime"])


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------

@app.route("/sessions")
def sessions() -> str:
    db = get_db()
    library_id = _library_id(db)
    query = _clean(request.args.get("q"))
    platform_id = _safe_int(request.args.get("platform"), 1)
    playthrough_filter = _clean(request.args.get("playthrough"))
    date_from = _normalise_date(request.args.get("date_from"))
    date_to = _normalise_date(request.args.get("date_to"))
    clauses = ["g.library_id = ?"]
    params: list[Any] = [library_id]
    if query:
        clauses.append("g.title LIKE ?")
        params.append(f"%{query}%")
    if platform_id:
        clauses.append("s.platform_id = ?")
        params.append(platform_id)
    if playthrough_filter == "unassigned":
        clauses.append("s.playthrough_id IS NULL")
    elif playthrough_filter:
        selected_playthrough_id = _safe_int(playthrough_filter, 1)
        if _playthrough_for_library(db, selected_playthrough_id, library_id) is not None:
            clauses.append("s.playthrough_id = ?")
            params.append(selected_playthrough_id)
        else:
            playthrough_filter = ""
    if date_from:
        clauses.append("s.session_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("s.session_date <= ?")
        params.append(date_to)
    rows = db.execute(
        f"""
        SELECT s.*, g.title, g.id AS game_id, p.name AS platform_name,
               pt.run_number, pt.name AS playthrough_name
        FROM sessions s
        JOIN games g ON g.id = s.game_id
        LEFT JOIN platforms p ON p.id = s.platform_id
        LEFT JOIN playthroughs pt ON pt.id = s.playthrough_id
        WHERE {' AND '.join(clauses)}
        ORDER BY s.session_date DESC, s.id DESC
        """,
        params,
    ).fetchall()
    games = db.execute(
        "SELECT id, title FROM games WHERE library_id = ? ORDER BY sort_title COLLATE NOCASE",
        (library_id,),
    ).fetchall()
    platforms = db.execute(
        "SELECT id, name FROM platforms ORDER BY name COLLATE NOCASE"
    ).fetchall()
    playthroughs = _playthroughs_for_library(db, library_id)
    return render_template(
        "sessions.html",
        sessions=rows,
        games=games,
        platforms=platforms,
        session_platforms=platforms,
        playthroughs=playthroughs,
        session_types=SESSION_TYPE_VALUES,
        mode_values=MODE_VALUES,
        query=query,
        platform_id=platform_id,
        playthrough_filter=playthrough_filter,
        date_from=date_from,
        date_to=date_to,
    )


def _create_session(db: sqlite3.Connection, game_id: str, values: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO sessions (
            game_id, playthrough_id, session_date, start_time, end_time, duration_seconds,
            platform_id, session_type, mode, progress_before, progress_after,
            progress_percent, chapter, objective, participants, location,
            achievements, mood, notes, created_at, updated_at
        ) VALUES (
            :game_id, :playthrough_id, :session_date, :start_time, :end_time, :duration_seconds,
            :platform_id, :session_type, :mode, :progress_before, :progress_after,
            :progress_percent, :chapter, :objective, :participants, :location,
            :achievements, :mood, :notes, :created_at, :updated_at
        )
        """,
        {"game_id": game_id, **values, "created_at": now, "updated_at": now},
    )


def _sync_playthroughs_from_sessions(
    db: sqlite3.Connection,
    session_values: list[dict[str, Any]],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    first_dates: dict[int, str] = {}
    completed_dates: dict[int, str] = {}
    for values in session_values:
        playthrough_id = values.get("playthrough_id")
        if playthrough_id is None:
            continue
        first_dates.setdefault(playthrough_id, values["session_date"])
        first_dates[playthrough_id] = min(
            first_dates[playthrough_id],
            values["session_date"],
        )
        if (
            values["session_type"] == "completion"
            or (
                values["progress_percent"] is not None
                and values["progress_percent"] >= 100
            )
        ):
            completed_dates[playthrough_id] = max(
                completed_dates.get(playthrough_id, values["session_date"]),
                values["session_date"],
            )
    for playthrough_id, started_date in first_dates.items():
        db.execute(
            """
            UPDATE playthroughs
            SET started_date = CASE
                    WHEN started_date = '' THEN ?
                    ELSE started_date
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (started_date, now, playthrough_id),
        )
    for playthrough_id, completed_date in completed_dates.items():
        db.execute(
            """
            UPDATE playthroughs
            SET status = 'completed',
                completed_date = CASE
                    WHEN completed_date = '' THEN ?
                    ELSE completed_date
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (completed_date, now, playthrough_id),
        )


@app.route("/session/new", methods=["POST"])
def new_session() -> Response:
    db = get_db()
    game_id = _clean(request.form.get("game_id"))
    game = _game_in_library(db, game_id, _library_id(db))
    if game is None:
        flash("Choose a valid game for the session.", "error")
        return redirect(request.referrer or url_for("sessions"))
    session_values, error = _parse_session_entries(db, request.form, game_id)
    if error:
        flash(error, "error")
        return redirect(request.referrer or url_for("sessions"))
    for values in session_values:
        _create_session(db, game_id, values)
    _sync_playthroughs_from_sessions(db, session_values)
    if not game["start_date"] and session_values:
        db.execute(
            "UPDATE games SET start_date = ? WHERE id = ?",
            (session_values[0]["session_date"], game_id),
        )
    completed_dates = [
        values["session_date"]
        for values in session_values
        if values["session_type"] == "completion"
        or (
            values["progress_percent"] is not None
            and values["progress_percent"] >= 100
        )
    ]
    if completed_dates:
        completion_date = max(completed_dates)
        db.execute(
            """
            UPDATE games
            SET status = 'completed',
                completion_date = COALESCE(NULLIF(completion_date, ''), ?)
            WHERE id = ?
            """,
            (completion_date, game_id),
        )
        _record_status(db, game_id, "completed", completion_date)
    db.commit()
    if len(session_values) == 1:
        flash("Play session recorded.", "success")
    else:
        flash(f"Play sessions recorded across {len(session_values)} days.", "success")
    return redirect(request.referrer or url_for("sessions"))


@app.route("/session/<int:session_id>/edit", methods=["GET", "POST"])
def edit_session(session_id: int) -> str | Response:
    db = get_db()
    session_row = db.execute(
        """
        SELECT s.*, g.title, g.id AS game_id
        FROM sessions s JOIN games g ON g.id = s.game_id
        WHERE s.id = ? AND g.library_id = ?
        """,
        (session_id, _library_id(db)),
    ).fetchone()
    if session_row is None:
        abort(404)
    if request.method == "GET":
        return render_template(
            "session_form.html",
            session=session_row,
            games=db.execute(
                "SELECT id, title FROM games WHERE library_id = ? ORDER BY sort_title COLLATE NOCASE",
                (_library_id(db),),
            ).fetchall(),
            platforms=db.execute(
                "SELECT id, name FROM platforms ORDER BY name COLLATE NOCASE"
            ).fetchall(),
            playthroughs=_playthroughs_for_library(db, _library_id(db)),
            session_types=SESSION_TYPE_VALUES,
            mode_values=MODE_VALUES,
        )
    game_id = _clean(request.form.get("game_id")) or session_row["game_id"]
    if _game_in_library(db, game_id, _library_id(db)) is None:
        flash("Choose a valid game for the session.", "error")
        return redirect(url_for("edit_session", session_id=session_id))
    values, error = _parse_session_form(db, request.form, game_id)
    if error:
        flash(error, "error")
        return redirect(url_for("edit_session", session_id=session_id))
    db.execute(
        """
        UPDATE sessions SET
            game_id = :game_id, playthrough_id = :playthrough_id,
            session_date = :session_date, start_time = :start_time,
            end_time = :end_time, duration_seconds = :duration_seconds,
            platform_id = :platform_id, session_type = :session_type, mode = :mode,
            progress_before = :progress_before, progress_after = :progress_after,
            progress_percent = :progress_percent, chapter = :chapter, objective = :objective,
            participants = :participants, location = :location, achievements = :achievements,
            mood = :mood, notes = :notes, updated_at = :updated_at
        WHERE id = :session_id
        """,
        {
            "game_id": game_id,
            **values,
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    _sync_playthroughs_from_sessions(db, [values])
    db.commit()
    flash("Play session updated.", "success")
    return redirect(url_for("sessions"))


@app.route("/session/<int:session_id>/delete", methods=["POST"])
def delete_session(session_id: int) -> Response:
    db = get_db()
    db.execute(
        """
        DELETE FROM sessions
        WHERE id IN (
            SELECT s.id FROM sessions s
            JOIN games g ON g.id = s.game_id
            WHERE s.id = ? AND g.library_id = ?
        )
        """,
        (session_id, _library_id(db)),
    )
    db.commit()
    flash("Play session deleted.", "success")
    return redirect(request.referrer or url_for("sessions"))


# ---------------------------------------------------------------------------
# Statistics, activity, and index
# ---------------------------------------------------------------------------

@app.route("/stats")
def stats() -> str:
    db = get_db()
    library_id = _library_id(db)
    sessions_by_year = [
        dict(row)
        for row in db.execute(
            """
            SELECT SUBSTR(s.session_date, 1, 4) AS year,
                   ROUND(COALESCE(SUM(s.duration_seconds), 0) / 3600.0, 1) AS hours,
                   COUNT(*) AS sessions
            FROM sessions s JOIN games g ON g.id = s.game_id
            WHERE g.library_id = ?
            GROUP BY year ORDER BY year
            """,
            (library_id,),
        ).fetchall()
    ]
    platform_hours = [
        dict(row)
        for row in db.execute(
            """
            SELECT COALESCE(p.name, 'Unspecified') AS label,
                   ROUND(COALESCE(SUM(s.duration_seconds), 0) / 3600.0, 1) AS hours
            FROM sessions s
            JOIN games g ON g.id = s.game_id
            LEFT JOIN platforms p ON p.id = s.platform_id
            WHERE g.library_id = ?
            GROUP BY label ORDER BY hours DESC, label
            """,
            (library_id,),
        ).fetchall()
    ]
    game_rows = db.execute(
        """
        SELECT g.id, g.title, g.genres,
               COUNT(s.id) AS session_count,
               COALESCE(SUM(s.duration_seconds), 0) AS seconds
        FROM games g
        LEFT JOIN sessions s ON s.game_id = g.id
        WHERE g.library_id = ?
        GROUP BY g.id
        ORDER BY seconds DESC, g.sort_title COLLATE NOCASE
        """,
        (library_id,),
    ).fetchall()
    genre_hours: defaultdict[str, float] = defaultdict(float)
    for row in game_rows:
        genres = _split_values(row["genres"]) or ["Unspecified"]
        for genre in genres:
            genre_hours[genre] += float(row["seconds"] or 0) / 3600
    genre_data = [
        {"label": label, "hours": round(hours, 1)}
        for label, hours in sorted(
            genre_hours.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
    status_counts = [
        dict(row)
        for row in db.execute(
            "SELECT status AS label, COUNT(*) AS count FROM games WHERE library_id = ? GROUP BY status",
            (library_id,),
        ).fetchall()
    ]
    total_games = db.execute(
        "SELECT COUNT(*) FROM games WHERE library_id = ?", (library_id,)
    ).fetchone()[0]
    completed_games = db.execute(
        "SELECT COUNT(*) FROM games WHERE library_id = ? AND status = 'completed'",
        (library_id,),
    ).fetchone()[0]
    total_seconds = db.execute(
        """
        SELECT COALESCE(SUM(s.duration_seconds), 0)
        FROM sessions s JOIN games g ON g.id = s.game_id
        WHERE g.library_id = ?
        """,
        (library_id,),
    ).fetchone()[0]
    average_rating = db.execute(
        "SELECT AVG(rating) FROM games WHERE library_id = ? AND rating IS NOT NULL",
        (library_id,),
    ).fetchone()[0]
    return render_template(
        "stats.html",
        sessions_by_year=sessions_by_year,
        platform_hours=platform_hours,
        genre_data=genre_data,
        status_counts=status_counts,
        top_games=[dict(row) for row in game_rows[:10]],
        total_games=total_games,
        completed_games=completed_games,
        completion_rate=round((completed_games / total_games) * 100, 1) if total_games else 0,
        total_seconds=total_seconds,
        average_rating=round(float(average_rating), 1) if average_rating is not None else None,
    )


@app.route("/activity")
def activity() -> str:
    db = get_db()
    library_id = _library_id(db)
    rows = db.execute(
        """
        SELECT s.*, g.title, g.id AS game_id, p.name AS platform_name,
               pt.run_number, pt.name AS playthrough_name
        FROM sessions s
        JOIN games g ON g.id = s.game_id
        LEFT JOIN platforms p ON p.id = s.platform_id
        LEFT JOIN playthroughs pt ON pt.id = s.playthrough_id
        WHERE g.library_id = ?
        ORDER BY s.session_date DESC, s.id DESC
        """,
        (library_id,),
    ).fetchall()
    daily: dict[str, dict[str, int]] = {}
    for row in rows:
        item = daily.setdefault(row["session_date"], {"sessions": 0, "seconds": 0})
        item["sessions"] += 1
        item["seconds"] += int(row["duration_seconds"] or 0)
    active_dates = sorted(daily)
    longest_streak = _longest_streak(active_dates)
    current_streak = _current_streak(daily)
    return render_template(
        "activity.html",
        rows=rows[:150],
        daily=daily,
        total_sessions=len(rows),
        active_days=len(daily),
        current_streak=current_streak,
        longest_streak=longest_streak,
    )


def _longest_streak(dates: list[str]) -> int:
    if not dates:
        return 0
    longest = 1
    run = 1
    for previous, current in zip(dates, dates[1:]):
        first = datetime.strptime(previous, "%Y-%m-%d").date()
        second = datetime.strptime(current, "%Y-%m-%d").date()
        if second - first == timedelta(days=1):
            run += 1
        else:
            longest = max(longest, run)
            run = 1
    return max(longest, run)


def _current_streak(daily: dict[str, dict[str, int]]) -> int:
    streak = 0
    cursor = date.today()
    while cursor.isoformat() in daily:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@app.route("/index")
def index() -> str:
    db = get_db()
    library_id = _library_id(db)
    games = _list_games(db, library_id)
    platform_counts = [
        dict(row)
        for row in db.execute(
            """
            SELECT p.id, p.name, COUNT(gp.game_id) AS count
            FROM platforms p
            JOIN game_platforms gp ON gp.platform_id = p.id
            JOIN games g ON g.id = gp.game_id
            WHERE g.library_id = ?
            GROUP BY p.id ORDER BY p.name COLLATE NOCASE
            """,
            (library_id,),
        ).fetchall()
    ]
    counters: dict[str, Counter[str]] = {
        "genres": Counter(),
        "developers": Counter(),
        "publishers": Counter(),
        "series": Counter(),
        "tags": Counter(),
    }
    for game in games:
        for field in ("genres", "developers", "publishers"):
            counters[field].update(_split_values(game.get(field)))
        if _clean(game.get("series")):
            counters["series"].update([_clean(game["series"])])
        counters["tags"].update(_game_tags(db, game["id"]))
    return render_template(
        "index.html",
        platform_counts=platform_counts,
        groups={
            key: [
                {"name": name, "count": count}
                for name, count in sorted(
                    counter.items(),
                    key=lambda item: (-item[1], item[0].casefold()),
                )
            ]
            for key, counter in counters.items()
        },
    )


# ---------------------------------------------------------------------------
# Backup and shutdown
# ---------------------------------------------------------------------------

@app.route("/backup", methods=["POST"])
def create_backup() -> Response:
    username = _current_user_or_abort()
    try:
        path = _backup_database(username)
    except (OSError, sqlite3.Error) as exc:
        flash(f"Backup failed: {exc}", "error")
        return redirect(request.referrer or url_for("dashboard"))
    flash("Backup created." if path else "Nothing to back up yet.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/shutdown-backup", methods=["POST"])
def shutdown_backup() -> Response:
    username = _current_user_or_abort()
    try:
        path = _backup_database(username)
    except (OSError, sqlite3.Error) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": path})


@app.errorhandler(404)
def not_found(_error: Any) -> tuple[str, int]:
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("LUDARIUM_PORT", "5000"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=port, debug=False)
