from dataclasses import dataclass
import sqlite3

from .envelope import Envelope
from .validate import VerifiedItem


@dataclass(frozen=True)
class ArchiveEntry:
    receipt_id: int
    envelope: Envelope


class IntakeArchive:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS received_items (
                receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                station TEXT NOT NULL,
                revision_id INTEGER NOT NULL,
                issue_id INTEGER NOT NULL,
                digest TEXT NOT NULL,
                body BLOB NOT NULL,
                raw BLOB NOT NULL,
                UNIQUE (batch_id, station, issue_id)
            )
        ''')
        columns = {
            row[1] for row in self.connection.execute('PRAGMA table_info(received_items)')
        }
        if 'version' not in columns:
            self.connection.execute('ALTER TABLE received_items ADD COLUMN version INTEGER NOT NULL DEFAULT 1')

    @staticmethod
    def _restore(row) -> ArchiveEntry:
        receipt_id, *envelope_fields = row
        return ArchiveEntry(receipt_id, Envelope(*envelope_fields))

    def record(self, item: VerifiedItem) -> ArchiveEntry:
        envelope = item.envelope
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing = db.execute('''
                SELECT receipt_id, batch_id, station, revision_id, issue_id, digest, body, raw, version
                FROM received_items WHERE batch_id = ? AND station = ? AND issue_id = ?
            ''', (envelope.batch_id, envelope.station, envelope.issue_id)).fetchone()
            if existing is not None:
                stored = self._restore(existing)
                if (stored.envelope.identity != envelope.identity
                        or stored.envelope.body != envelope.body):
                    raise ValueError('issue identity already belongs to another body')
                return stored
            inserted = db.execute('''
                INSERT INTO received_items
                    (batch_id, station, revision_id, issue_id, digest, body, raw, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (*envelope.identity, envelope.digest, envelope.body, envelope.raw,
                  envelope.version))
            entry = ArchiveEntry(inserted.lastrowid, envelope)
        return entry

    def get(self, receipt_id: int) -> ArchiveEntry | None:
        row = self.connection.execute('''
            SELECT receipt_id, batch_id, station, revision_id, issue_id, digest, body, raw, version
            FROM received_items WHERE receipt_id = ?
        ''', (receipt_id,)).fetchone()
        return self._restore(row) if row is not None else None
