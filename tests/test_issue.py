from fractions import Fraction
from pathlib import Path
import sqlite3
import tempfile
import unittest

from batch import BatchStore, get_batch, register
from demo import BATCH, CORRECTION_ROWS, LEFT_ROWS, NAMES, request
from intake import IntakeArchive, receive
from intake.envelope import parse_envelope
from report import ReportStore
from risk import assess
from station import IssueStore, RevisionStore, issue, load_revision, reissue, revise
from tests.test_risk import pack_complete


class IssueTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.catalog_db = self.connect('catalog.sqlite')
        self.station_db = self.connect('station.sqlite')
        self.catalog = BatchStore(self.catalog_db)
        self.revisions = RevisionStore(self.station_db)
        self.issues = IssueStore(self.station_db)
        for store in (self.catalog, self.revisions, self.issues):
            store.initialize()
        self.batch = register(self.catalog, BATCH, NAMES, '1/4')

    def connect(self, filename):
        db = sqlite3.connect(self.root / filename)
        self.addCleanup(db.close)
        return db

    def first(self):
        return revise(self.catalog, self.revisions, BATCH, '甲', LEFT_ROWS)

    def correct(self, old):
        return revise(self.catalog, self.revisions, BATCH, '甲', CORRECTION_ROWS,
                      parent_id=old.revision_id)

    def center_with_companion(self):
        db = self.connect('center.sqlite')
        archive, reports = IntakeArchive(db), ReportStore(db)
        archive.initialize()
        reports.initialize()
        companion = receive(archive, pack_complete('乙', [(1, 1)] * 4))
        return archive, reports, companion.receipt_id

    def assess_basis(self, center, frozen, state_index):
        archive, reports, companion_id = center
        received = receive(archive, frozen.raw)
        masses = tuple(int(index == state_index) for index in range(4))
        return assess(archive, reports, request(BATCH, (received.receipt_id, companion_id), masses)).report.draft

    def test_exact_revision(self):
        old = self.first()
        frozen = issue(self.issues, old.revision_id)
        corrected = self.correct(old)
        new = issue(self.issues, corrected.revision_id)
        self.assertEqual(parse_envelope(frozen.raw).revision_id, old.revision_id)
        self.assertEqual(parse_envelope(new.raw).revision_id, corrected.revision_id)
        self.assertNotEqual(new.issue_id, frozen.issue_id)
        self.assertEqual(reissue(self.issues, frozen.issue_id).raw, frozen.raw)
        self.assertEqual(issue(self.issues, old.revision_id), frozen)
        self.assertEqual(load_revision(self.revisions, corrected.revision_id).parent_id, old.revision_id)

    def test_registration(self):
        self.assertEqual(register(self.catalog, BATCH, NAMES[::-1], Fraction(1, 4)), self.batch)
        for names, line in ((('A', 'OTHER'), '1/4'), (NAMES, '1/5'),
                            (('A', 'A'), '1/4'), (NAMES, '5/4'), (NAMES, '1/0')):
            with self.subTest(names=names, line=line), self.assertRaises(ValueError):
                register(self.catalog, BATCH, names, line)
        with self.assertRaises(ValueError):
            register(self.catalog, 'NEW', NAMES, '-1/4')
        with self.assertRaises(KeyError):
            get_batch(self.catalog, 'NEW')
        self.assertEqual(get_batch(self.catalog, BATCH), self.batch)

    def test_explicit_revision(self):
        old = self.first()
        corrected = self.correct(old)
        new = issue(self.issues, corrected.revision_id)
        frozen = issue(self.issues, old.revision_id)
        self.assertEqual(parse_envelope(frozen.raw).revision_id, old.revision_id)
        self.assertEqual(reissue(self.issues, frozen.issue_id), frozen)
        center = self.center_with_companion()
        self.assertEqual(self.assess_basis(center, frozen, 3).risk, Fraction(1))
        self.assertEqual(self.assess_basis(center, new, 3).status, 'incompatible')
        with self.assertRaises(KeyError):
            issue(self.issues, 999)
        with self.assertRaises(KeyError):
            reissue(self.issues, 999)

    def test_joint_support(self):
        rows = LEFT_ROWS + (((0, 1), '7', False, True), ((1, 0), '0', True, True))
        old = revise(self.catalog, self.revisions, BATCH, '甲', rows)
        corrected = self.correct(old)
        center = self.center_with_companion()
        for revision, expected in ((old, (0, None, None, 1)), (corrected, (None, 0, 1, None))):
            frozen = issue(self.issues, revision.revision_id)
            for index, risk in enumerate(expected):
                with self.subTest(revision=revision.revision_id, state=index):
                    result = self.assess_basis(center, frozen, index)
                    self.assertEqual(result.risk, risk)
                    self.assertEqual(result.status, 'incompatible' if risk is None else 'established')

    def test_reopen_initialize(self):
        old = self.first()
        corrected = self.correct(old)
        frozen = issue(self.issues, old.revision_id)
        catalog = BatchStore(self.connect('catalog.sqlite'))
        db = self.connect('station.sqlite')
        revisions, issues = RevisionStore(db), IssueStore(db)
        for store in (catalog, revisions, issues):
            store.initialize()
            store.initialize()
        self.assertEqual(get_batch(catalog, BATCH), self.batch)
        self.assertEqual(load_revision(revisions, old.revision_id), old)
        self.assertEqual(load_revision(revisions, corrected.revision_id), corrected)
        self.assertEqual(reissue(issues, frozen.issue_id), frozen)
        self.assertEqual(issue(issues, old.revision_id), frozen)

    def test_invalid_trial(self):
        old = self.first()
        invalid = LEFT_ROWS + (((1, 0), '-1', True, True),)
        with self.assertRaises(ValueError):
            revise(self.catalog, self.revisions, BATCH, '甲', invalid, parent_id=old.revision_id)
        self.assertEqual(self.station_db.execute('SELECT count(*) FROM station_revisions').fetchone(), (1,))
        self.assertEqual(self.station_db.execute('SELECT count(*) FROM station_trials').fetchone(), (2,))
        self.assertEqual(issue(self.issues, old.revision_id).revision_id, old.revision_id)

    def test_foreign_parent(self):
        old = self.first()
        register(self.catalog, 'OTHER', NAMES, '1/4')
        for batch_id, station in (('OTHER', '甲'), (BATCH, '乙')):
            with self.subTest(batch=batch_id, station=station), self.assertRaises(ValueError):
                revise(self.catalog, self.revisions, batch_id, station, LEFT_ROWS,
                       parent_id=old.revision_id)
        with self.assertRaises(ValueError):
            self.first()
        self.assertEqual(self.station_db.execute('SELECT count(*) FROM station_revisions').fetchone(), (1,))
        self.assertEqual(load_revision(self.revisions, old.revision_id), old)
        self.assertEqual(issue(self.issues, old.revision_id).revision_id, old.revision_id)
