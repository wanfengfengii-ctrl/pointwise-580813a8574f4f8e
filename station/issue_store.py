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

    def freeze_item(self, revision_id: int, encode: Callable[[int], bytes]) -> FrozenIssue:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing = db.execute('''
                SELECT issue_id, revision_id, raw FROM station_issues WHERE revision_id = ?
            ''', (revision_id,)).fetchone()
            if existing is not None:
                return FrozenIssue(*existing)
            last_issue, = db.execute('SELECT COALESCE(MAX(issue_id), 0) FROM station_issues').fetchone()
            issue_id = last_issue + 1
            raw = encode(issue_id)
            db.execute('''
                INSERT INTO station_issues (issue_id, revision_id, raw) VALUES (?, ?, ?)
            ''', (issue_id, revision_id, raw))
        return FrozenIssue(issue_id, revision_id, raw)

    def load_issue(self, issue_id: int) -> FrozenIssue | None:
        row = self.connection.execute('''
            SELECT issue_id, revision_id, raw FROM station_issues WHERE issue_id = ?
        ''', (issue_id,)).fetchone()
        return FrozenIssue(*row) if row is not None else None
