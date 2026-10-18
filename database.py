import aiosqlite

class Database:
    def __init__(self, path="vantahq.sqlite3"):
        self.path = path

    async def initialize(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY (guild_id, key))""")
            await db.execute("""CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, action TEXT,
                target_id INTEGER, moderator_id INTEGER, reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS tickets (
                guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id), UNIQUE(channel_id))""")
            await db.commit()

    async def set_setting(self, guild_id, key, value):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO settings(guild_id,key,value) VALUES(?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value", (guild_id, key, str(value)))
            await db.commit()

    async def get_setting(self, guild_id, key):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def add_case(self, guild_id, action, target_id, moderator_id, reason):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO cases(guild_id,action,target_id,moderator_id,reason) VALUES(?,?,?,?,?)", (guild_id, action, target_id, moderator_id, reason))
            await db.commit()

    async def get_ticket(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def create_ticket(self, guild_id, user_id, channel_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO tickets(guild_id,user_id,channel_id) VALUES(?,?,?)", (guild_id, user_id, channel_id))
            await db.commit()

    async def delete_ticket_by_channel(self, channel_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM tickets WHERE channel_id=?", (channel_id,))
            await db.commit()
