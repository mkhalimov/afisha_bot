import logging
from datetime import datetime
from typing import Optional

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS announcement_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator_user_id INTEGER NOT NULL,
  creator_username TEXT,
  title TEXT,
  category TEXT,
  event_date TEXT,        -- YYYY-MM-DD
  time_start TEXT,        -- HH:MM
  time_end TEXT,          -- HH:MM
  location TEXT,
  description TEXT,
  organizer TEXT,
  image_file_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',  -- draft/pending/approved/rejected/published
  admin_message_id INTEGER,              -- message id in admin chat
  reject_reason TEXT,
  channel_message_id INTEGER,
  published_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


async def init_db():
    import os
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE_SQL)
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


async def upsert_draft(user_id: int, username: Optional[str], data: dict) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM announcement_drafts WHERE creator_user_id=? AND status='draft' ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cur.fetchone()
        if row:
            draft_id = row[0]
            await db.execute(
                """
                UPDATE announcement_drafts
                SET creator_username=?, title=?, category=?, event_date=?, time_start=?, time_end=?,
                    location=?, description=?, organizer=?, updated_at=?
                WHERE id=?
                """,
                (
                    username,
                    data.get("title"),
                    data.get("category"),
                    data.get("event_date"),
                    data.get("time_start"),
                    data.get("time_end"),
                    data.get("location"),
                    data.get("description"),
                    data.get("organizer"),
                    now,
                    draft_id,
                )
            )
        else:
            cur = await db.execute(
                """
                INSERT INTO announcement_drafts
                (creator_user_id, creator_username, title, category, event_date, time_start, time_end,
                 location, description, organizer, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    user_id, username,
                    data.get("title"),
                    data.get("category"),
                    data.get("event_date"),
                    data.get("time_start"),
                    data.get("time_end"),
                    data.get("location"),
                    data.get("description"),
                    data.get("organizer"),
                    now, now,
                )
            )
            draft_id = cur.lastrowid

        await db.commit()
        return draft_id


async def set_draft_image(draft_id: int, image_file_id: str):
    """Save image file_id without changing status (stays 'draft' until actually submitted)."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET image_file_id=?, updated_at=? WHERE id=?",
            (image_file_id, now, draft_id)
        )
        await db.commit()


async def set_draft_pending(draft_id: int):
    """Flip status to 'pending' when the draft is actually sent to the admin queue."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='pending', updated_at=? WHERE id=?",
            (now, draft_id)
        )
        await db.commit()


async def set_admin_message_id(draft_id: int, admin_message_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET admin_message_id=?, updated_at=? WHERE id=?",
            (admin_message_id, now, draft_id)
        )
        await db.commit()


async def get_draft(draft_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM announcement_drafts WHERE id=?", (draft_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_draft_approved(draft_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='approved', updated_at=? WHERE id=?",
            (now, draft_id)
        )
        await db.commit()


async def set_draft_rejected(draft_id: int, reason: str):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='rejected', reject_reason=?, updated_at=? WHERE id=?",
            (reason, now, draft_id)
        )
        await db.commit()


async def set_draft_published(draft_id: int, channel_message_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE announcement_drafts
            SET status='published', channel_message_id=?, published_at=?, updated_at=?
            WHERE id=?
            """,
            (channel_message_id, now, now, draft_id)
        )
        await db.commit()


async def get_user_drafts(user_id: int) -> list[dict]:
    """Return user's drafts newest-first (up to 20)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM announcement_drafts WHERE creator_user_id=? ORDER BY id DESC LIMIT 20",
            (user_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def reset_draft_to_edit(draft_id: int):
    """Reset a rejected draft back to 'draft' status so user can resubmit."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='draft', image_file_id=NULL, reject_reason=NULL, updated_at=? WHERE id=?",
            (now, draft_id)
        )
        await db.commit()


async def count_user_pending_drafts(user_id: int) -> int:
    """Return number of drafts in 'pending' (awaiting moderation) status for user."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM announcement_drafts WHERE creator_user_id=? AND status='pending'",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def delete_draft(draft_id: int):
    """Permanently delete a draft record."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM announcement_drafts WHERE id=?", (draft_id,))
        await db.commit()
