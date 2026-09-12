import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from db.models import Commitment, CommitmentStatus, UserGoogleAuth, utc_now


class Database:
    def __init__(self, db_path: str = "commitment_radar.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initializes database tables and indexes."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS commitments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    guild_id TEXT,
                    message_id TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    task_title TEXT NOT NULL,
                    recipient TEXT,
                    deadline_utc TEXT NOT NULL,
                    relative_deadline_text TEXT,
                    context_snippet TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    calendar_event_id TEXT,
                    calendar_event_link TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Multi-User Google OAuth Token Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_google_auth (
                    discord_user_id TEXT PRIMARY KEY,
                    google_email TEXT,
                    token_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Migration check for existing databases
            async with db.execute("PRAGMA table_info(commitments)") as cursor:
                cols = [row[1] for row in await cursor.fetchall()]
                if "calendar_event_id" not in cols:
                    await db.execute("ALTER TABLE commitments ADD COLUMN calendar_event_id TEXT")
                if "calendar_event_link" not in cols:
                    await db.execute("ALTER TABLE commitments ADD COLUMN calendar_event_link TEXT")

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_commitments_status_deadline 
                ON commitments (status, deadline_utc)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_commitments_user 
                ON commitments (user_id, status)
            """)
            await db.commit()

    async def add_commitment(self, commitment: Commitment) -> Commitment:
        """Inserts a new commitment and returns it with its generated id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO commitments (
                    user_id, user_name, channel_id, guild_id, message_id,
                    raw_text, task_title, recipient, deadline_utc,
                    relative_deadline_text, context_snippet, status,
                    calendar_event_id, calendar_event_link,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                commitment.user_id,
                commitment.user_name,
                commitment.channel_id,
                commitment.guild_id,
                commitment.message_id,
                commitment.raw_text,
                commitment.task_title,
                commitment.recipient,
                commitment.deadline_utc.isoformat(),
                commitment.relative_deadline_text,
                commitment.context_snippet,
                commitment.status.value if hasattr(commitment.status, 'value') else commitment.status,
                commitment.calendar_event_id,
                commitment.calendar_event_link,
                commitment.created_at.isoformat(),
                commitment.updated_at.isoformat()
            ))
            await db.commit()
            commitment.id = cursor.lastrowid
            return commitment

    async def get_commitment_by_id(self, commitment_id: int) -> Optional[Commitment]:
        """Retrieves a single commitment by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM commitments WHERE id = ?", (commitment_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_commitment(row)
        return None

    async def get_due_alerts(self, lead_minutes: int = 30) -> List[Commitment]:
        """Finds PENDING commitments whose deadline falls within the notification window."""
        cutoff = (utc_now() + timedelta(minutes=lead_minutes)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM commitments
                WHERE status = 'PENDING' AND deadline_utc <= ?
                ORDER BY deadline_utc ASC
            """, (cutoff,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_commitment(r) for r in rows]

    async def update_status(self, commitment_id: int, new_status: CommitmentStatus) -> bool:
        """Updates the status and updated_at timestamp of a commitment."""
        now = utc_now().isoformat()
        status_val = new_status.value if hasattr(new_status, 'value') else new_status
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE commitments
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (status_val, now, commitment_id))
            await db.commit()
            return cursor.rowcount > 0

    async def update_deadline(self, commitment_id: int, new_deadline: datetime) -> bool:
        """Postpones or changes the deadline and sets status back to PENDING if needed."""
        now = utc_now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE commitments
                SET deadline_utc = ?, status = 'PENDING', updated_at = ?
                WHERE id = ?
            """, (new_deadline.isoformat(), now, commitment_id))
            await db.commit()
            return cursor.rowcount > 0

    async def get_user_commitments(self, user_id: str, limit: int = 10) -> List[Commitment]:
        """Gets the most recent commitments for a specific user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM commitments
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_commitment(r) for r in rows]

    async def get_active_commitments_for_user(self, user_id: str) -> List[Commitment]:
        """Gets all non-completed/non-cancelled commitments for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM commitments
                WHERE user_id = ? AND status IN ('PENDING', 'NOTIFIED', 'SNOOZED')
                ORDER BY deadline_utc ASC
            """, (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_commitment(r) for r in rows]

    async def update_calendar_event(self, commitment_id: int, event_id: str, event_link: str) -> bool:
        """Associates a Google Calendar event ID and link with a commitment."""
        now = utc_now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE commitments
                SET calendar_event_id = ?, calendar_event_link = ?, updated_at = ?
                WHERE id = ?
            """, (event_id, event_link, now, commitment_id))
            await db.commit()
            return cursor.rowcount > 0

    async def save_user_google_auth(
        self,
        discord_user_id: str,
        token_json: str,
        google_email: Optional[str] = None
    ) -> bool:
        """Saves or updates OAuth tokens for a specific Discord user."""
        now = utc_now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_google_auth (discord_user_id, google_email, token_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE SET
                    google_email = excluded.google_email,
                    token_json = excluded.token_json,
                    updated_at = excluded.updated_at
            """, (discord_user_id, google_email, token_json, now, now))
            await db.commit()
            return True

    async def get_user_google_auth(self, discord_user_id: str) -> Optional[UserGoogleAuth]:
        """Retrieves stored Google OAuth credentials for a specific Discord user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_google_auth WHERE discord_user_id = ?",
                (discord_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return UserGoogleAuth(
                        discord_user_id=row["discord_user_id"],
                        google_email=row["google_email"],
                        token_json=row["token_json"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"])
                    )
        return None

    async def delete_user_google_auth(self, discord_user_id: str) -> bool:
        """Removes stored Google OAuth credentials for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_google_auth WHERE discord_user_id = ?",
                (discord_user_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    def _row_to_commitment(self, row: aiosqlite.Row) -> Commitment:
        # Check if keys exist in row for backward-compatibility with custom queries
        keys = row.keys() if hasattr(row, 'keys') else []
        cal_id = row["calendar_event_id"] if "calendar_event_id" in keys else None
        cal_link = row["calendar_event_link"] if "calendar_event_link" in keys else None

        return Commitment(
            id=row["id"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            message_id=row["message_id"],
            raw_text=row["raw_text"],
            task_title=row["task_title"],
            recipient=row["recipient"],
            deadline_utc=datetime.fromisoformat(row["deadline_utc"]),
            relative_deadline_text=row["relative_deadline_text"] or "",
            context_snippet=row["context_snippet"],
            status=CommitmentStatus(row["status"]),
            calendar_event_id=cal_id,
            calendar_event_link=cal_link,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
