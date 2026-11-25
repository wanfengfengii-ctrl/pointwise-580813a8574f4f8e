import json
import sqlite3
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from batch import BatchStore
from intake.envelope import parse_envelope
from station import IssueStore, RevisionStore, issue, issue_sum, load_revision, reissue, revise
from station.distribution import build_distribution
from sum_review_fixture import (BATCH, CORRECTED_SUPPORTS, LEFT_SUPPORTS, NAMES, ROWS,
                                RIGHT_SUPPORTS, source_fixture)


class SumIssueTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.catalog_db = self.connect('catalog.sqlite')
        self.left_db = self.connect('station-a.sqlite')
        self.right_db = self.connect('station-b.sqlite')
        self.catalog = BatchStore(self.catalog_db)
        self.left_revisions = RevisionStore(self.left_db)
        self.right_revisions = RevisionStore(self.right_db)
        self.left_issues = IssueStore(self.left_db)
        self.right_issues = IssueStore(self.right_db)
        for store in (self.catalog, self.left_revisions, self.right_revisions,
                      self.left_issues, self.right_issues):
            store.initialize()
        self.left, self.right, self.corrected = source_fixture(
            self.catalog, self.left_revisions, self.right_revisions)

    def connect(self, filename):
        db = sqlite3.connect(self.root / filename)
        self.addCleanup(db.close)
        return db

    def test_v2_envelope_shape(self):
        frozen = issue_sum(self.left_issues, self.left.revision_id, LEFT_SUPPORTS)
        envelope = parse_envelope(frozen.raw)
        self.assertEqual(envelope.version, 2)
        body = json.loads(envelope.body)
        self.assertEqual(body['references'], list(NAMES))
        self.assertEqual([entry['state'] for entry in body['distributions']],
                         [[0, 0], [0, 1], [1, 0], [1, 1]])
        # State 00 is a uniform [0,1] interval; state 11 is a point at zero.
        state00 = body['distributions'][0]
        self.assertEqual(state00['match']['components'], [['0', '1', '1']])
        self.assertEqual(state00['exceed']['components'], [])
        state11 = body['distributions'][3]
        self.assertEqual(state11['match']['components'], [['0', '1']])
        self.assertEqual(state11['exceed']['components'], [['0', '1']])

    def test_single_v2_per_revision_and_equivalent_endpoints(self):
        first = issue_sum(self.left_issues, self.left.revision_id, LEFT_SUPPORTS)
        # Exactly equivalent rational spellings return the original id and bytes.
        respelled = issue_sum(self.left_issues, self.left.revision_id,
                              (('0/1', '1/1'), ('0/2', '0/2')))
        self.assertEqual(respelled, first)
        with self.assertRaisesRegex(ValueError, 'different supports'):
            issue_sum(self.left_issues, self.left.revision_id, ((0, 1), (1, 1)))
        # A later V2 on another revision still gets a fresh id.
        second = issue_sum(self.left_issues, self.corrected.revision_id, CORRECTED_SUPPORTS)
        self.assertNotEqual(second.issue_id, first.issue_id)

    def test_v1_and_v2_coexist_and_reissue(self):
        v1 = issue(self.left_issues, self.left.revision_id)
        v2 = issue_sum(self.left_issues, self.left.revision_id, LEFT_SUPPORTS)
        self.assertNotEqual(v1.issue_id, v2.issue_id)
        self.assertEqual(parse_envelope(v1.raw).version, 1)
        self.assertEqual(parse_envelope(v2.raw).version, 2)
        self.assertEqual(reissue(self.left_issues, v2.issue_id).raw, v2.raw)
        self.assertEqual(reissue(self.left_issues, v1.issue_id).raw, v1.raw)
        with self.assertRaises(KeyError):
            reissue(self.left_issues, 9999)

    def test_shared_issue_id_sequence(self):
        left_v1 = issue(self.left_issues, self.left.revision_id)
        left_v2 = issue_sum(self.left_issues, self.corrected.revision_id, CORRECTED_SUPPORTS)
        right_v2 = issue_sum(self.right_issues, self.right.revision_id, RIGHT_SUPPORTS)
        # Within one station the V1 and V2 sequences never collide.
        self.assertNotEqual(left_v1.issue_id, left_v2.issue_id)
        self.assertEqual({left_v1.issue_id, left_v2.issue_id}, {1, 2})
        # Stations are independent databases and may reuse numbers.
        self.assertEqual(right_v2.issue_id, 1)

    def test_support_validation(self):
        with self.assertRaisesRegex(ValueError, 'cover every trial row'):
            issue_sum(self.left_issues, self.left.revision_id, ((0, 1),))
        with self.assertRaisesRegex(ValueError, 'lo <= hi'):
            issue_sum(self.left_issues, self.left.revision_id, ((1, 0), (0, 0)))
        with self.assertRaises(ValueError):
            issue_sum(self.left_issues, self.left.revision_id, (('nope', 1), (0, 0)))
        with self.assertRaises(ValueError):
            issue_sum(self.left_issues, self.left.revision_id, None)

    def test_empty_revision_needs_empty_supports(self):
        empty = revise(self.catalog, self.right_revisions, BATCH, "乙", (),
                       parent_id=self.right.revision_id)
        frozen = issue_sum(self.right_issues, empty.revision_id, ())
        body = json.loads(parse_envelope(frozen.raw).body)
        self.assertTrue(all(not entry['match']['components']
                            and not entry['exceed']['components']
                            for entry in body['distributions']))
        with self.assertRaisesRegex(ValueError, 'cover every trial row'):
            issue_sum(self.right_issues, empty.revision_id, ((0, 1),))

    def test_unmatched_and_zero_weight_rows_excluded_but_covered(self):
        rows = (
            ((0, 0), 4, True, False),
            ((0, 0), 2, True, False),
            ((0, 0), 5, False, True),
            ((1, 1), 0, True, True),
            ((1, 1), 3, True, True),
        )
        supports = ((0, 1), (2, 2), (0, 1), (0, 0), (1, 3))
        revision = revise(self.catalog, self.left_revisions, BATCH, "甲", rows,
                          parent_id=self.left.revision_id)
        distribution = build_distribution(load_revision(self.left_revisions, revision.revision_id),
                                          supports)
        state00 = distribution.states[0]
        self.assertEqual(state00.match.intervals[0].mass, Fraction(4))
        self.assertEqual(state00.match.atoms[0].position, Fraction(2))
        self.assertEqual(state00.match.atoms[0].mass, Fraction(2))
        self.assertEqual(state00.exceed.total(), Fraction(0))
        state11 = distribution.states[3]
        self.assertEqual(state11.match.intervals[0].mass, Fraction(3))
        self.assertEqual(state11.exceed.intervals[0].mass, Fraction(3))

    def test_distribution_keeps_weight_scale(self):
        scale = Fraction(7, 3)
        rows = tuple((state, scale * weight, match, exceed)
                     for state, weight, match, exceed in ROWS)
        revision = revise(self.catalog, self.right_revisions, BATCH, "乙", rows,
                          parent_id=self.right.revision_id)
        distribution = build_distribution(
            load_revision(self.right_revisions, revision.revision_id), RIGHT_SUPPORTS)
        self.assertEqual(distribution.states[0].match.intervals[0].mass, scale)
        self.assertEqual(distribution.states[3].match.intervals[0].mass, scale)
        self.assertEqual(distribution.states[3].exceed.intervals[0].mass, scale)

    def test_reopen_persists_v2(self):
        frozen = issue_sum(self.left_issues, self.left.revision_id, LEFT_SUPPORTS)
        db = self.connect('station-a.sqlite')
        reloaded_issues = IssueStore(db)
        reloaded_issues.initialize()
        self.assertEqual(reissue(reloaded_issues, frozen.issue_id).raw, frozen.raw)
