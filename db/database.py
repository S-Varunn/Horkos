import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from db.models import Commitment, CommitmentStatus, DiningInquiry, DiningInquiryStatus, utc_now


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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
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
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _row_to_commitment(self, row: aiosqlite.Row) -> Commitment:
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
