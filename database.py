import asyncpg
import logging
from datetime import datetime
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    # ──────────────────────────────────────────
    #  BAĞLANTI & TABLO OLUŞTURMA
    # ──────────────────────────────────────────
    async def connect(self):
        for attempt in range(5):
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=2, max_size=10)
                await self._create_tables()
                logger.info("PostgreSQL bağlantısı kuruldu.")
                return
            except Exception as e:
                logger.warning(f"DB bağlantı denemesi {attempt + 1}/5 başarısız: {e}")
                import asyncio; await asyncio.sleep(3)
        raise RuntimeError("PostgreSQL'e bağlanılamadı!")

    async def _create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id      BIGINT PRIMARY KEY,
                    username     TEXT,
                    first_name   TEXT,
                    join_date    TIMESTAMP DEFAULT NOW(),
                    warn_count   INTEGER   DEFAULT 0,
                    invite_count INTEGER   DEFAULT 0,
                    total_messages INTEGER DEFAULT 0,
                    is_muted     BOOLEAN   DEFAULT FALSE,
                    mute_until   TIMESTAMP,
                    is_banned    BOOLEAN   DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS warnings (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT NOT NULL,
                    admin_id   BIGINT,
                    reason     TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS invite_links (
                    link       TEXT PRIMARY KEY,
                    owner_id   BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS invites (
                    id         SERIAL PRIMARY KEY,
                    inviter_id BIGINT NOT NULL,
                    invited_id BIGINT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    stat_date      DATE PRIMARY KEY DEFAULT CURRENT_DATE,
                    new_members    INTEGER DEFAULT 0,
                    left_members   INTEGER DEFAULT 0,
                    total_messages INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS message_activity (
                    user_id       BIGINT,
                    activity_date DATE DEFAULT CURRENT_DATE,
                    message_count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, activity_date)
                );
            """)

    # ──────────────────────────────────────────
    #  KULLANICI İŞLEMLERİ
    # ──────────────────────────────────────────
    async def upsert_user(self, user_id: int, username: Optional[str], first_name: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET username = $2, first_name = $3
            """, user_id, username, first_name)

    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def get_user_by_username(self, username: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username
            )

    async def set_banned(self, user_id: int, banned: bool):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_banned = $2 WHERE user_id = $1", user_id, banned
            )

    async def set_mute(self, user_id: int, until: Optional[datetime]):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET is_muted = $2, mute_until = $3 WHERE user_id = $1
            """, user_id, until is not None, until)

    async def get_muted_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, first_name, username, mute_until
                FROM users WHERE is_muted = TRUE
                ORDER BY mute_until ASC
            """)

    # ──────────────────────────────────────────
    #  UYARI İŞLEMLERİ
    # ──────────────────────────────────────────
    async def add_warn(self, user_id: int, admin_id: int, reason: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT first_name FROM users WHERE user_id = $1", user_id)
            first_name = row["first_name"] if row else "Kullanıcı"
            await conn.execute("""
                INSERT INTO warnings (user_id, admin_id, reason, first_name)
                VALUES ($1, $2, $3, $4)
            """, user_id, admin_id, reason, first_name)
            await conn.execute("""
                UPDATE users SET warn_count = warn_count + 1 WHERE user_id = $1
            """, user_id)
            return await conn.fetchval(
                "SELECT warn_count FROM users WHERE user_id = $1", user_id
            ) or 1

    async def remove_warn(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM warnings WHERE id = (
                    SELECT id FROM warnings WHERE user_id = $1
                    ORDER BY created_at DESC LIMIT 1
                )
            """, user_id)
            await conn.execute("""
                UPDATE users SET warn_count = GREATEST(warn_count - 1, 0)
                WHERE user_id = $1
            """, user_id)

    async def reset_warns(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM warnings WHERE user_id = $1", user_id)
            await conn.execute("UPDATE users SET warn_count = 0 WHERE user_id = $1", user_id)

    async def get_warnings(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT * FROM warnings WHERE user_id = $1
                ORDER BY created_at DESC
            """, user_id)

    async def get_warn_count(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT warn_count FROM users WHERE user_id = $1", user_id
            ) or 0

    async def get_recent_warnings(self, limit: int = 10):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT w.user_id, w.reason, w.created_at, u.first_name
                FROM warnings w
                LEFT JOIN users u ON u.user_id = w.user_id
                ORDER BY w.created_at DESC LIMIT $1
            """, limit)

    # ──────────────────────────────────────────
    #  DAVET İŞLEMLERİ
    # ──────────────────────────────────────────
    async def store_invite_link(self, link: str, owner_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO invite_links (link, owner_id)
                VALUES ($1, $2)
                ON CONFLICT (link) DO NOTHING
            """, link, owner_id)

    async def get_invite_link_owner(self, link: str) -> Optional[int]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT owner_id FROM invite_links WHERE link = $1", link
            )

    async def add_invite(self, inviter_id: int, invited_id: int):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO invites (inviter_id, invited_id)
                    VALUES ($1, $2)
                """, inviter_id, invited_id)
                await conn.execute("""
                    UPDATE users SET invite_count = invite_count + 1
                    WHERE user_id = $1
                """, inviter_id)
            except asyncpg.UniqueViolationError:
                pass  # Aynı kullanıcı iki kez sayılmasın

    async def get_invite_leaderboard(self, limit: int = 10):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, username, first_name, invite_count
                FROM users WHERE invite_count > 0
                ORDER BY invite_count DESC LIMIT $1
            """, limit)

    # ──────────────────────────────────────────
    #  MESAJ & AKTİVİTE
    # ──────────────────────────────────────────
    async def increment_message_count(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET total_messages = total_messages + 1
                WHERE user_id = $1
            """, user_id)
            await conn.execute("""
                INSERT INTO message_activity (user_id, activity_date, message_count)
                VALUES ($1, CURRENT_DATE, 1)
                ON CONFLICT (user_id, activity_date) DO UPDATE
                SET message_count = message_activity.message_count + 1
            """, user_id)
            await conn.execute("""
                INSERT INTO daily_stats (stat_date, total_messages)
                VALUES (CURRENT_DATE, 1)
                ON CONFLICT (stat_date) DO UPDATE
                SET total_messages = daily_stats.total_messages + 1
            """)

    async def update_daily_new_member(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO daily_stats (stat_date, new_members)
                VALUES (CURRENT_DATE, 1)
                ON CONFLICT (stat_date) DO UPDATE
                SET new_members = daily_stats.new_members + 1
            """)

    async def update_daily_left_member(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO daily_stats (stat_date, left_members)
                VALUES (CURRENT_DATE, 1)
                ON CONFLICT (stat_date) DO UPDATE
                SET left_members = daily_stats.left_members + 1
            """)

    async def get_top_active_today(self, limit: int = 3):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT ma.user_id, ma.message_count, u.username, u.first_name
                FROM message_activity ma
                JOIN users u ON u.user_id = ma.user_id
                WHERE ma.activity_date = CURRENT_DATE
                ORDER BY ma.message_count DESC LIMIT $1
            """, limit)

    # ──────────────────────────────────────────
    #  GENEL İSTATİSTİK
    # ──────────────────────────────────────────
    async def get_group_stats(self) -> dict:
        async with self.pool.acquire() as conn:
            total_users    = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            total_messages = await conn.fetchval("SELECT COALESCE(SUM(total_messages),0) FROM users") or 0
            total_invites  = await conn.fetchval("SELECT COALESCE(SUM(invite_count),0) FROM users") or 0
            total_warns    = await conn.fetchval("SELECT COUNT(*) FROM warnings") or 0
            today          = await conn.fetchrow(
                "SELECT * FROM daily_stats WHERE stat_date = CURRENT_DATE"
            )
        return {
            "total_users":    total_users,
            "total_messages": total_messages,
            "total_invites":  total_invites,
            "total_warns":    total_warns,
            "today":          dict(today) if today else {},
        }
