from contextlib import closing
from fractions import Fraction
from pathlib import Path
import sqlite3
import tempfile
import unittest

from batch import BatchStore
from demo import BATCH, LEFT_ROWS, request, sample_issues
from intake import IntakeArchive, receive
from report import ReportStore, read
from risk import assess
from station import IssueStore, RevisionStore, issue, revise


class PublishTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'center.sqlite'

    def stores(self, db):
        archive, reports = IntakeArchive(db), ReportStore(db)
        archive.initialize()
        reports.initialize()
        return archive, reports

    def delivered(self, archive):
        with sample_issues(self.root) as (a, b, correction):
            left, right = receive(archive, a.raw), receive(archive, b.raw)
        return left, right, correction

    def counts(self, db):
        return db.execute('''
            SELECT (SELECT count(*) FROM signed_reports),
                   (SELECT count(*) FROM sign_receipts)
        ''').fetchone()

    def test_receipt_failure(self):
        with closing(sqlite3.connect(self.path)) as db:
            archive, reports = self.stores(db)
            left, right, _ = self.delivered(archive)
            candidate = request(BATCH, (left.receipt_id, right.receipt_id))
            db.execute('''
                CREATE TRIGGER reject_receipt BEFORE INSERT ON sign_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'receipt rejected at write');
                END
            ''')
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt rejected at write'):
                assess(archive, reports, candidate)
            self.assertEqual(self.counts(db), (0, 0))
            self.assertFalse(db.in_transaction)
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(self.counts(reopened), (0, 0))
            reopened.execute('DROP TRIGGER reject_receipt')
            archive, reports = self.stores(reopened)
            retried = assess(archive, reports, candidate)
            self.assertEqual(self.counts(reopened), (1, 1))
            self.assertEqual(retried.report.draft.risk, Fraction(1, 3))
            self.assertEqual(read(reports, retried.report.report_id), retried)
            self.assertEqual(retried.receipt.report_id, retried.report.report_id)

    def test_reopen_history(self):
        with closing(sqlite3.connect(self.path)) as db:
            archive, reports = self.stores(db)
            left, right, correction = self.delivered(archive)
            old_ids = (left.receipt_id, right.receipt_id)
            old = assess(archive, reports, request(BATCH, old_ids))
            corrected = receive(archive, correction.raw)
            new_ids = (corrected.receipt_id, right.receipt_id)
            new = assess(archive, reports, request(BATCH, new_ids))
            self.assertEqual(old.report.draft.risk, Fraction(1, 3))
            self.assertEqual(old.report.draft.disposition, 'isolate')
            self.assertEqual(new.report.draft.status, 'incompatible')
            self.assertEqual(new.report.draft.risk, None)
            self.assertEqual(new.report.draft.disposition, 'review')
            self.assertNotEqual(old.receipt, new.receipt)
        with closing(sqlite3.connect(self.path)) as reopened:
            self.stores(reopened)
            archive, reports = self.stores(reopened)
            self.assertEqual(archive.get(left.receipt_id), left)
            self.assertEqual(archive.get(corrected.receipt_id), corrected)
            recovered = read(reports, old.report.report_id)
            for signed, expected_ids in ((recovered, old_ids), (read(reports, new.report.report_id), new_ids)):
                self.assertEqual(tuple(source.receipt_id for source in signed.report.draft.sources),
                                 expected_ids)
            self.assertEqual(recovered, old)
            self.assertEqual(read(reports, new.report.report_id), new)
            self.assertEqual(self.counts(reopened), (2, 2))

    def test_equal_value_revision(self):
        with closing(sqlite3.connect(self.path)) as db:
            archive, reports = self.stores(db)
            left, right, _ = self.delivered(archive)
            old = assess(archive, reports, request(BATCH, (left.receipt_id, right.receipt_id)))
            with (closing(sqlite3.connect(self.root / 'catalog.sqlite')) as cat_db,
                  closing(sqlite3.connect(self.root / 'station-a.sqlite')) as station_db):
                identical = revise(BatchStore(cat_db), RevisionStore(station_db), BATCH, '甲', LEFT_ROWS,
                                   parent_id=left.envelope.revision_id)
                frozen = issue(IssueStore(station_db), identical.revision_id)
            new_item = receive(archive, frozen.raw)
            new = assess(archive, reports, request(BATCH, (new_item.receipt_id, right.receipt_id)))
            self.assertNotEqual(new_item.receipt_id, left.receipt_id)
            self.assertNotEqual(new_item.envelope.issue_id, left.envelope.issue_id)
            self.assertEqual(old.report.draft.risk, Fraction(1, 3))
            self.assertEqual(new.report.draft.risk, Fraction(1, 3))
        with closing(sqlite3.connect(self.path)) as reopened:
            _, reports = self.stores(reopened)
            for accepted, item in ((old, left), (new, new_item)):
                recovered = read(reports, accepted.report.report_id)
                self.assertEqual(recovered, accepted)
                first, second = recovered.report.draft.sources
                self.assertEqual((first.receipt_id, first.revision_id, first.issue_id, first.digest),
                                 (item.receipt_id, item.envelope.revision_id, item.envelope.issue_id,
                                  item.envelope.digest))
                self.assertEqual(second.receipt_id, right.receipt_id)

    def test_unknown_report(self):
        with closing(sqlite3.connect(self.path)) as db:
            _, reports = self.stores(db)
            self.assertIsNone(read(reports, 999))
            self.assertEqual(self.counts(db), (0, 0))
