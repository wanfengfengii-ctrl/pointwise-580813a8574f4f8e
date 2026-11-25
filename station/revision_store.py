from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from batch.references import make_reference_pair
from .trials import TrialRecord, TrialSet


@dataclass(frozen=True)
class StoredRevision:
    revision_id: int
    batch_id: str
    station: str
    parent_id: int | None
    trials: TrialSet


class RevisionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS station_revisions (
                revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                station TEXT NOT NULL,
                parent_id INTEGER REFERENCES station_revisions(revision_id),
                reference_a TEXT NOT NULL,
                reference_b TEXT NOT NULL CHECK (reference_a <> reference_b)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS station_initial_revision
                ON station_revisions(batch_id, station) WHERE parent_id IS NULL;
            CREATE TABLE IF NOT EXISTS station_trials (
                revision_id INTEGER NOT NULL REFERENCES station_revisions(revision_id),
                ordinal INTEGER NOT NULL,
                bit_a INTEGER NOT NULL CHECK (bit_a IN (0, 1)),
                bit_b INTEGER NOT NULL CHECK (bit_b IN (0, 1)),
                weight TEXT NOT NULL,
                matches INTEGER NOT NULL CHECK (matches IN (0, 1)),
                exceeds INTEGER NOT NULL CHECK (exceeds IN (0, 1)),
                PRIMARY KEY (revision_id, ordinal)
            );
        ''')

    def commit_revision(self, batch_id: str, station: str, parent_id: int | None,
                        trials: TrialSet) -> StoredRevision:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            if parent_id is None:
                initial = db.execute('''
                    SELECT revision_id FROM station_revisions
                    WHERE batch_id = ? AND station = ? AND parent_id IS NULL
                ''', (batch_id, station)).fetchone()
                if initial is not None:
                    raise ValueError('an initial revision already exists; select a parent')
            else:
                parent = db.execute('''
                    SELECT batch_id, station FROM station_revisions WHERE revision_id = ?
                ''', (parent_id,)).fetchone()
                if parent is None or tuple(parent) != (batch_id, station):
                    raise ValueError('parent must belong to this batch and station')
            header = db.execute('''
                INSERT INTO station_revisions
                    (batch_id, station, parent_id, reference_a, reference_b)
                VALUES (?, ?, ?, ?, ?)
            ''', (batch_id, station, parent_id, *trials.references.names))
            revision_id = header.lastrowid
            db.executemany('''
                INSERT INTO station_trials
                    (revision_id, ordinal, bit_a, bit_b, weight, matches, exceeds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                (revision_id, ordinal, *trial.state, str(trial.weight), trial.matches, trial.exceeds)
                for ordinal, trial in enumerate(trials.rows)
            ))
        return StoredRevision(revision_id, batch_id, station, parent_id, trials)

    def load_revision(self, revision_id: int) -> StoredRevision | None:
        header = self.connection.execute('''
            SELECT batch_id, station, parent_id, reference_a, reference_b
            FROM station_revisions WHERE revision_id = ?
        ''', (revision_id,)).fetchone()
        if header is None:
            return None
        batch_id, station, parent_id, first, second = header
        rows = self.connection.execute('''
            SELECT bit_a, bit_b, weight, matches, exceeds FROM station_trials
            WHERE revision_id = ? ORDER BY ordinal
        ''', (revision_id,))
        trials = TrialSet(
            make_reference_pair((first, second)),
            tuple(TrialRecord((a, b), Fraction(weight), bool(matches), bool(exceeds))
                  for a, b, weight, matches, exceeds in rows),
        )
        return StoredRevision(revision_id, batch_id, station, parent_id, trials)
