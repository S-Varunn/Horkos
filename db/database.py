import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from db.models import Commitment, CommitmentStatus, DiningInquiry, DiningInquiryStatus, UserGoogleAuth, UserCalendarTemplate, ChannelCalendarTemplate, utc_now


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

            # Multi-User Custom Calendar Template Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_calendar_templates (
                    discord_user_id TEXT PRIMARY KEY,
                    title_template TEXT NOT NULL,
                    completed_template TEXT NOT NULL,
                    description_template TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Per-Channel Custom Calendar Template Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channel_calendar_templates (
                    channel_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    channel_name TEXT,
                    title_template TEXT NOT NULL,
                    completed_template TEXT NOT NULL,
                    description_template TEXT,
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dining_inquiries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    guild_id TEXT,
                    raw_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'WAITING',
                    chosen_cuisine TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_dining_channel_status
                ON dining_inquiries (channel_id, status)
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

    async def get_due_alerts(self, lead_minutes: int = 10) -> List[Commitment]:
        """Finds PENDING commitments whose deadline is upcoming and falls within the notification window."""
        now_iso = utc_now().isoformat()
        cutoff_iso = (utc_now() + timedelta(minutes=lead_minutes)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM commitments
                WHERE status = 'PENDING'
                  AND deadline_utc > ?
                  AND deadline_utc <= ?
                ORDER BY deadline_utc ASC
            """, (now_iso, cutoff_iso)) as cursor:
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

    async def get_all_active_commitments(self) -> List[Commitment]:
        """Gets all non-completed/non-cancelled commitments across all users."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM commitments
                WHERE status IN ('PENDING', 'NOTIFIED', 'SNOOZED')
                ORDER BY deadline_utc ASC
            """) as cursor:
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

    async def save_user_calendar_template(
        self,
        discord_user_id: str,
        title_template: str,
        completed_template: Optional[str] = None,
        description_template: Optional[str] = None
    ) -> UserCalendarTemplate:
        """Saves or updates a user's custom calendar event templates."""
        now = utc_now().isoformat()
        comp_tpl = completed_template or "[Done] {task}"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_calendar_templates (
                    discord_user_id, title_template, completed_template,
                    description_template, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE SET
                    title_template = excluded.title_template,
                    completed_template = excluded.completed_template,
                    description_template = excluded.description_template,
                    updated_at = excluded.updated_at
            """, (discord_user_id, title_template, comp_tpl, description_template, now, now))
            await db.commit()

        return UserCalendarTemplate(
            discord_user_id=discord_user_id,
            title_template=title_template,
            completed_template=comp_tpl,
            description_template=description_template,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now)
        )

    async def get_user_calendar_template(self, discord_user_id: str) -> Optional[UserCalendarTemplate]:
        """Retrieves a user's custom calendar event template if configured."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_calendar_templates WHERE discord_user_id = ?",
                (discord_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return UserCalendarTemplate(
                        discord_user_id=row["discord_user_id"],
                        title_template=row["title_template"],
                        completed_template=row["completed_template"],
                        description_template=row["description_template"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"])
                    )
        return None

    async def delete_user_calendar_template(self, discord_user_id: str) -> bool:
        """Deletes a user's custom calendar event template (reverting to default)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_calendar_templates WHERE discord_user_id = ?",
                (discord_user_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def save_channel_calendar_template(
        self,
        channel_id: str,
        title_template: str,
        completed_template: Optional[str] = None,
        description_template: Optional[str] = None,
        guild_id: Optional[str] = None,
        channel_name: Optional[str] = None
    ) -> ChannelCalendarTemplate:
        """Saves or updates a channel's custom calendar event template."""
        now = utc_now().isoformat()
        comp_tpl = completed_template or "[Done] {task}"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO channel_calendar_templates (
                    channel_id, guild_id, channel_name, title_template, completed_template,
                    description_template, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    guild_id = COALESCE(excluded.guild_id, channel_calendar_templates.guild_id),
                    channel_name = COALESCE(excluded.channel_name, channel_calendar_templates.channel_name),
                    title_template = excluded.title_template,
                    completed_template = excluded.completed_template,
                    description_template = excluded.description_template,
                    updated_at = excluded.updated_at
            """, (channel_id, guild_id, channel_name, title_template, comp_tpl, description_template, now, now))
            await db.commit()

        return ChannelCalendarTemplate(
            channel_id=channel_id,
            guild_id=guild_id,
            channel_name=channel_name,
            title_template=title_template,
            completed_template=comp_tpl,
            description_template=description_template,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now)
        )

    async def get_channel_calendar_template(self, channel_id: str) -> Optional[ChannelCalendarTemplate]:
        """Retrieves a channel's custom calendar event template if configured."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM channel_calendar_templates WHERE channel_id = ?",
                (channel_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return ChannelCalendarTemplate(
                        channel_id=row["channel_id"],
                        guild_id=row["guild_id"],
                        channel_name=row["channel_name"],
                        title_template=row["title_template"],
                        completed_template=row["completed_template"],
                        description_template=row["description_template"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"])
                    )
        return None

    async def delete_channel_calendar_template(self, channel_id: str) -> bool:
        """Deletes a channel's custom calendar event template."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM channel_calendar_templates WHERE channel_id = ?",
                (channel_id,)
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
    async def add_dining_inquiry(self, inquiry: DiningInquiry) -> DiningInquiry:
        """Inserts a new dining inquiry and assigns its generated ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO dining_inquiries (
                    channel_id, message_id, user_id, user_name, guild_id,
                    raw_text, status, chosen_cuisine, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inquiry.channel_id,
                inquiry.message_id,
                inquiry.user_id,
                inquiry.user_name,
                inquiry.guild_id,
                inquiry.raw_text,
                inquiry.status.value if hasattr(inquiry.status, 'value') else inquiry.status,
                inquiry.chosen_cuisine,
                inquiry.created_at.isoformat(),
                inquiry.updated_at.isoformat()
            ))
            await db.commit()
            inquiry.id = cursor.lastrowid
            return inquiry

    async def get_active_dining_inquiry_for_channel(self, channel_id: str) -> Optional[DiningInquiry]:
        """Gets the most recent waiting dining inquiry in a channel."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM dining_inquiries
                WHERE channel_id = ? AND status = 'WAITING'
                ORDER BY created_at DESC
                LIMIT 1
            """, (channel_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_dining_inquiry(row)
        return None

    async def update_dining_inquiry_status(
        self,
        inquiry_id: int,
        status: DiningInquiryStatus,
        chosen_cuisine: Optional[str] = None
    ) -> bool:
        """Updates status and optionally chosen cuisine for a dining inquiry."""
        now = utc_now().isoformat()
        status_val = status.value if hasattr(status, 'value') else status
        async with aiosqlite.connect(self.db_path) as db:
            if chosen_cuisine is not None:
                cursor = await db.execute("""
                    UPDATE dining_inquiries
                    SET status = ?, chosen_cuisine = ?, updated_at = ?
                    WHERE id = ?
                """, (status_val, chosen_cuisine, now, inquiry_id))
            else:
                cursor = await db.execute("""
                    UPDATE dining_inquiries
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status_val, now, inquiry_id))
            await db.commit()
            return cursor.rowcount > 0

    def _row_to_dining_inquiry(self, row: aiosqlite.Row) -> DiningInquiry:
        return DiningInquiry(
            id=row["id"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            guild_id=row["guild_id"],
            raw_text=row["raw_text"],
            status=DiningInquiryStatus(row["status"]),
            chosen_cuisine=row["chosen_cuisine"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    async def get_recent_resolved_dining_inquiry(
        self,
        channel_id: str,
        within_minutes: int = 3
    ) -> Optional[DiningInquiry]:
        """Gets the most recently resolved dining plan in a channel within the history window."""
        cutoff = (utc_now() - timedelta(minutes=within_minutes)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM dining_inquiries
                WHERE channel_id = ? AND status = 'RESOLVED' AND updated_at >= ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (channel_id, cutoff)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_dining_inquiry(row)
        return None
