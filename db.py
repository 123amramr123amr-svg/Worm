"""قاعدة بيانات SQLite: الإعدادات، المستخدمون، المحادثات، الرسائل، الملفات."""
import json

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    username TEXT,
    first_name TEXT,
    current_conversation_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    summarized_up_to INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    filename TEXT,
    path TEXT,
    mime TEXT,
    size INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(SCHEMA)
        for key, value in config.DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value),
            )
        await db.commit()


# ---------------- الإعدادات ----------------

async def get_all_settings() -> dict:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {row["key"]: row["value"] for row in rows}


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        await db.commit()


# ---------------- مزوّدو API ----------------

async def get_profiles() -> list:
    settings = await get_all_settings()
    try:
        profiles = json.loads(settings.get("profiles", "[]"))
    except (ValueError, TypeError):
        return []
    return profiles if isinstance(profiles, list) else []


async def save_profiles(profiles: list) -> None:
    await set_setting("profiles", json.dumps(profiles, ensure_ascii=False))


# ---------------- المستخدمون ----------------

async def upsert_user(user_id: int, chat_id: int, username: str, first_name: str) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, chat_id, username, first_name) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, "
            "username=excluded.username, first_name=excluded.first_name, "
            "last_seen=datetime('now')",
            (user_id, chat_id, username, first_name),
        )
        await db.commit()


# ---------------- المحادثات ----------------

async def create_conversation(user_id: int) -> int:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO conversations(user_id) VALUES(?)", (user_id,)
        )
        conv_id = cur.lastrowid
        await db.execute(
            "UPDATE users SET current_conversation_id=? WHERE user_id=?",
            (conv_id, user_id),
        )
        await db.commit()
        return conv_id


async def set_current_conversation(user_id: int, conv_id: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE users SET current_conversation_id=? WHERE user_id=?",
            (conv_id, user_id),
        )
        await db.commit()


async def get_current_conversation_id(user_id: int):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT current_conversation_id FROM users WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row and row[0]:
            cur = await db.execute(
                "SELECT id FROM conversations WHERE id=?", (row[0],)
            )
            if await cur.fetchone():
                return row[0]
    return None


async def get_or_create_conversation(user_id: int) -> int:
    conv_id = await get_current_conversation_id(user_id)
    if conv_id:
        return conv_id
    return await create_conversation(user_id)


async def list_conversations(user_id: int) -> list:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.*, COUNT(m.id) AS message_count FROM conversations c "
            "LEFT JOIN messages m ON m.conversation_id = c.id "
            "WHERE c.user_id = ? GROUP BY c.id ORDER BY c.updated_at DESC",
            (user_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_conversation(conv_id: int):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM conversations WHERE id=?", (conv_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_conversation(conv_id: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "DELETE FROM messages WHERE conversation_id=?", (conv_id,)
        )
        await db.execute(
            "DELETE FROM conversations WHERE id=?", (conv_id,)
        )
        await db.execute(
            "UPDATE users SET current_conversation_id=NULL "
            "WHERE current_conversation_id=?",
            (conv_id,),
        )
        await db.commit()


async def clear_conversation_messages(conv_id: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "DELETE FROM messages WHERE conversation_id=?", (conv_id,)
        )
        await db.execute(
            "UPDATE conversations SET summary='', summarized_up_to=0 WHERE id=?",
            (conv_id,),
        )
        await db.commit()


async def set_summary(conv_id: int, summary: str, up_to: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE conversations SET summary=?, summarized_up_to=? WHERE id=?",
            (summary, up_to, conv_id),
        )
        await db.commit()


# ---------------- الرسائل ----------------

async def add_message(conversation_id: int, user_id: int, role: str, content: str) -> int:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO messages(conversation_id, user_id, role, content) "
            "VALUES(?,?,?,?)",
            (conversation_id, user_id, role, content),
        )
        msg_id = cur.lastrowid
        await db.execute(
            "UPDATE conversations SET updated_at=datetime('now') WHERE id=?",
            (conversation_id,),
        )
        if role == "user":
            cur = await db.execute(
                "SELECT title FROM conversations WHERE id=?", (conversation_id,)
            )
            row = await cur.fetchone()
            if row and not row[0]:
                title = " ".join(content.split())[:40]
                await db.execute(
                    "UPDATE conversations SET title=? WHERE id=?",
                    (title, conversation_id),
                )
        await db.commit()
        return msg_id


async def get_messages(conversation_id: int) -> list:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, role, content FROM messages "
            "WHERE conversation_id=? ORDER BY id ASC",
            (conversation_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


# ---------------- الملفات ----------------

async def add_file(user_id: int, filename: str, path: str, mime: str, size: int) -> None:
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT INTO files(user_id, filename, path, mime, size) "
            "VALUES(?,?,?,?,?)",
            (user_id, filename, path, mime, size),
        )
        await db.commit()
