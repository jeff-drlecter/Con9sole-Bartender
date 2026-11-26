"""Coalesce the publisher feed, Follow gateway and existing Update Publisher in one SQLite DB."""
from dataclasses import asdict
import json

from core.automatic_updates import Notice
from core.fc27_publication import Receipts
from core.sqlite_storage import connect_sqlite


class AutomaticReceipts(Receipts):
    def __init__(self, path, now):
        super().__init__(path)
        with connect_sqlite(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS auto_start (singleton INTEGER PRIMARY KEY, started REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS auto_news (
                    id INTEGER PRIMARY KEY, packet TEXT NOT NULL, parent INTEGER, stage TEXT NOT NULL,
                    available REAL NOT NULL, sent_id INTEGER);
                CREATE TABLE IF NOT EXISTS auto_alias (
                    channel INTEGER, alias TEXT, news INTEGER NOT NULL REFERENCES auto_news(id),
                    PRIMARY KEY(channel,alias));
                CREATE INDEX IF NOT EXISTS auto_due ON auto_news(stage,available);
            """)
            db.execute("INSERT OR IGNORE INTO auto_start VALUES (1,?)", (now,))
            self.started = db.execute("SELECT started FROM auto_start WHERE singleton=1").fetchone()[0]

    def seen(self, channel, alias):
        with connect_sqlite(self.path) as db:
            return db.execute("SELECT 1 FROM auto_alias WHERE channel=? AND alias=?", (channel, alias)).fetchone() is not None

    def observe(self, item, parent=None, *, now):
        if not item.keys:
            return
        marks = ",".join("?" for _ in item.keys)
        packet = json.dumps(asdict(item), ensure_ascii=False)
        old = item.published <= self.started
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            matches = db.execute(f"SELECT DISTINCT news FROM auto_alias WHERE channel=? AND alias IN ({marks})",
                                 (item.channel, *item.keys)).fetchall()
            if len(matches) > 1:
                db.executemany("UPDATE auto_news SET stage='held' WHERE id=? AND stage='pending'", matches)
                return
            if matches:
                key = matches[0][0]
                # Keep the dated publisher copy when it arrives after a native relay.
                db.execute("UPDATE auto_news SET parent=coalesce(parent,?),packet=CASE WHEN ? IS NULL THEN ? ELSE packet END,"
                           "stage=CASE WHEN ? THEN 'baseline' ELSE stage END WHERE id=? AND stage='pending'",
                           (parent, parent, packet, old, key))
            else:
                key = db.execute("INSERT INTO auto_news(packet,parent,stage,available) VALUES (?,?,?,?)",
                                 (packet, parent, "baseline" if old else "pending", now + 600)).lastrowid
            db.executemany("INSERT OR IGNORE INTO auto_alias VALUES (?,?,?)", [(item.channel, k, key) for k in item.keys])
            if not old:
                # Manual review/legacy delivery already owns an alias: never post a second recap.
                owner = "automatic:" + str(key)
                for alias in item.keys:
                    held = db.execute("SELECT owner FROM fc27_delivery_owner WHERE version=?", (alias,)).fetchone()
                    if held and held[0] not in (owner, "observed"):
                        db.execute("UPDATE auto_news SET stage='held' WHERE id=? AND stage='pending'", (key,))
                db.executemany("INSERT INTO fc27_delivery_owner VALUES (?,?) ON CONFLICT(version) "
                               "DO UPDATE SET owner=excluded.owner WHERE owner='observed'",
                               [(alias, owner) for alias in item.keys])

    def next(self, now):
        with connect_sqlite(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,packet,parent FROM auto_news WHERE stage='pending' AND available<=? "
                             "ORDER BY available,id LIMIT 1", (now,)).fetchone()
            if row:
                db.execute("UPDATE auto_news SET available=? WHERE id=?", (now + 3600, row[0]))
                item = Notice(**json.loads(row[1]))
                aliases = {v[0] for v in db.execute("SELECT alias FROM auto_alias WHERE news=?", (row[0],))}
                return row[0], item, row[2], aliases
        return None

    def claim_send(self, key, expected_parent):
        with connect_sqlite(self.path) as db:
            return bool(db.execute("UPDATE auto_news SET stage='posting' WHERE id=? AND stage='pending' "
                                   "AND parent IS ?", (key, expected_parent)).rowcount)

    def finish(self, key, stage, *, from_stage, message=None):
        with connect_sqlite(self.path) as db:
            db.execute("UPDATE auto_news SET stage=?,sent_id=? WHERE id=? AND stage=?",
                       (stage, message, key, from_stage))
