from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class StoredBatch:
    batch_id: str
    reference_a: str
    reference_b: str
    isolation_line: str


class BatchStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY NOT NULL,
                reference_a TEXT NOT NULL,
                reference_b TEXT NOT NULL CHECK (reference_a < reference_b),
                isolation_line TEXT NOT NULL
            )
        ''')

    def register_if_absent(self, batch: StoredBatch) -> StoredBatch:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            db.execute('''
                INSERT INTO batches (batch_id, reference_a, reference_b, isolation_line)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(batch_id) DO NOTHING
            ''', (batch.batch_id, batch.reference_a, batch.reference_b, batch.isolation_line))
            stored = self.load(batch.batch_id)
            if stored is None:
                raise sqlite3.IntegrityError('batch registration did not create an archive row')
        return stored

    def load(self, batch_id: str) -> StoredBatch | None:
        row = self.connection.execute('''
            SELECT batch_id, reference_a, reference_b, isolation_line
            FROM batches WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        return StoredBatch(*row) if row is not None else None
