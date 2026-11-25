from dataclasses import dataclass
import sqlite3
from typing import Callable


@dataclass(frozen=True)
class FrozenIssue:
    issue_id: int
    revision_id: int
    raw: bytes


class IssueStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS station_issues (
                issue_id INTEGER PRIMARY KEY,
                revision_id INTEGER UNIQUE NOT NULL REFERENCES station_revisions(revision_id),
                raw BLOB NOT NULL
            )
        ''')
        # V2 sum-reading issues live in their own table but draw issue ids from the
        # same station-wide sequence, so a reissue number uniquely names one item.
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS station_sum_issues (
                issue_id INTEGER PRIMARY KEY,
                revision_id INTEGER UNIQUE NOT NULL REFERENCES station_revisions(revision_id),
                supports TEXT NOT NULL,
                raw BLOB NOT NULL
            )
        ''')

    def _next_issue_id(self, db: sqlite3.Connection) -> int:
        last_v1, = db.execute('SELECT COALESCE(MAX(issue_id), 0) FROM station_issues').fetchone()
        last_v2, = db.execute('SELECT COALESCE(MAX(issue_id), 0) FROM station_sum_issues').fetchone()
        return max(last_v1, last_v2) + 1

    def freeze_item(self, revision_id: int, encode: Callable[[int], bytes]) -> FrozenIssue:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing = db.execute('''
                SELECT issue_id, revision_id, raw FROM station_issues WHERE revision_id = ?
            ''', (revision_id,)).fetchone()
            if existing is not None:
                return FrozenIssue(*existing)
            issue_id = self._next_issue_id(db)
            raw = encode(issue_id)
            db.execute('''
                INSERT INTO station_issues (issue_id, revision_id, raw) VALUES (?, ?, ?)
            ''', (issue_id, revision_id, raw))
        return FrozenIssue(issue_id, revision_id, raw)

    def freeze_sum_item(self, revision_id: int, supports_key: str,
                        encode: Callable[[int], bytes]) -> FrozenIssue:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing = db.execute('''
                SELECT issue_id, revision_id, raw FROM station_sum_issues WHERE revision_id = ?
            ''', (revision_id,)).fetchone()
            if existing is not None:
                stored_id, stored_revision, stored_raw = existing
                stored_supports, = db.execute('''
                    SELECT supports FROM station_sum_issues WHERE revision_id = ?
                ''', (revision_id,)).fetchone()
                if stored_supports != supports_key:
                    raise ValueError('revision already has a V2 issue with different supports; '
                                     'issue a new fixed revision to change the readings')
                return FrozenIssue(stored_id, stored_revision, stored_raw)
            issue_id = self._next_issue_id(db)
            raw = encode(issue_id)
            db.execute('''
                INSERT INTO station_sum_issues (issue_id, revision_id, supports, raw)
                VALUES (?, ?, ?, ?)
            ''', (issue_id, revision_id, supports_key, raw))
        return FrozenIssue(issue_id, revision_id, raw)

    def load_issue(self, issue_id: int) -> FrozenIssue | None:
        row = self.connection.execute('''
            SELECT issue_id, revision_id, raw FROM station_issues WHERE issue_id = ?
        ''', (issue_id,)).fetchone()
        if row is not None:
            return FrozenIssue(*row)
        row = self.connection.execute('''
            SELECT issue_id, revision_id, raw FROM station_sum_issues WHERE issue_id = ?
        ''', (issue_id,)).fetchone()
        return FrozenIssue(*row) if row is not None else None
