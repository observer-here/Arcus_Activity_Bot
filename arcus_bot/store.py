import sqlite3

from arcus_bot.config import DB_PATH, MAX_PER_CHAT


class Store:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watches (
                chat_id INTEGER NOT NULL,
                address TEXT NOT NULL,
                account_index INTEGER NOT NULL,
                PRIMARY KEY (chat_id, address, account_index)
            );
            CREATE TABLE IF NOT EXISTS seen (
                address TEXT NOT NULL,
                account_index INTEGER NOT NULL,
                trade_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (address, account_index, trade_id)
            );
            """
        )

    def add(self, chat_id, address, indexes):
        wallets = {row[0] for row in self.list(chat_id)}
        if address not in wallets and len(wallets) >= MAX_PER_CHAT:
            return None
        added = []
        for idx in indexes:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO watches(chat_id, address, account_index) VALUES (?,?,?)",
                (chat_id, address, idx),
            )
            if cur.rowcount:
                added.append(idx)
        self.conn.commit()
        return added

    def remove(self, chat_id, address, idx):
        if idx is None:
            cur = self.conn.execute(
                "DELETE FROM watches WHERE chat_id=? AND address=?",
                (chat_id, address),
            )
        else:
            cur = self.conn.execute(
                "DELETE FROM watches WHERE chat_id=? AND address=? AND account_index=?",
                (chat_id, address, idx),
            )
        self.conn.commit()
        return cur.rowcount

    def list(self, chat_id):
        return self.conn.execute(
            "SELECT address, account_index FROM watches WHERE chat_id=? ORDER BY address, account_index",
            (chat_id,),
        ).fetchall()

    def targets(self):
        return self.conn.execute(
            "SELECT DISTINCT address, account_index FROM watches"
        ).fetchall()

    def chats(self, address, idx):
        rows = self.conn.execute(
            "SELECT chat_id FROM watches WHERE address=? AND account_index=?",
            (address, idx),
        ).fetchall()
        return [row[0] for row in rows]

    def mark(self, address, idx, trade_id, created_at):
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO seen(address, account_index, trade_id, created_at) VALUES (?,?,?,?)",
            (address, idx, trade_id, int(created_at or 0)),
        )
        if cur.rowcount:
            cutoff = self.conn.execute(
                """
                SELECT created_at FROM seen
                WHERE address=? AND account_index=?
                ORDER BY created_at DESC LIMIT 1 OFFSET 299
                """,
                (address, idx),
            ).fetchone()
            if cutoff:
                self.conn.execute(
                    "DELETE FROM seen WHERE address=? AND account_index=? AND created_at < ?",
                    (address, idx, cutoff[0]),
                )
        self.conn.commit()
        return cur.rowcount == 1

    def latest(self, address, idx):
        row = self.conn.execute(
            "SELECT MAX(created_at) FROM seen WHERE address=? AND account_index=?",
            (address, idx),
        ).fetchone()
        return row[0] or 0


store = Store()
