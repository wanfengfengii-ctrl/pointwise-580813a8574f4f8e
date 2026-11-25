import hashlib
import json
import sqlite3
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from batch import BatchStore, JointPrior, make_reference_pair
from intake import IntakeArchive, get_received, receive
from report import ReportStore, read
from risk import AssessmentRequest, assess, assess_sum
from station import IssueStore, RevisionStore, issue, issue_sum, revise
from sum_review_fixture import (BATCH, CORRECTED_SUPPORTS, LEFT_SUPPORTS, LINE, NAMES,
                                POINT_LEFT_SUPPORTS, POINT_RIGHT_SUPPORTS, PRIOR, ROWS,
                                RIGHT_SUPPORTS, issue_sum_fixture, source_fixture)


def pack_sum(station, distributions, *, batch_id=BATCH, names=NAMES, issue_id=1, revision_id=1):
    """Hand-craft a V2 envelope so validation can be tested without a station."""
    identity = dict(batch_id=batch_id, station=station, revision_id=revision_id, issue_id=issue_id)
    body = json.dumps(dict(identity, references=list(names), distributions=distributions),
                      ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    outer = dict(identity, version=2, body=body, sha256=digest)
    return json.dumps(outer, sort_keys=True, separators=(',', ':')).encode('utf-8')


def point_state(state, match_atoms=(), exceed_atoms=(), match_intervals=(), exceed_intervals=()):
    def measure(atoms, intervals):
        components = [[str(position), str(mass)] for position, mass in atoms]
        components += [[str(lo), str(hi), str(mass)] for lo, hi, mass in intervals]
        return {'components': components}

    return {'state': list(state),
            'match': measure(match_atoms, match_intervals),
            'exceed': measure(exceed_atoms, exceed_intervals)}


class SumRiskTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.center = sqlite3.connect(self.root / 'center.sqlite')
        self.addCleanup(self.center.close)
        self.archive = IntakeArchive(self.center)
        self.reports = ReportStore(self.center)
        self.archive.initialize()
        self.reports.initialize()
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
        left_v2, right_v2, corrected_v2 = issue_sum_fixture(
            self.left_issues, self.right_issues, self.left, self.right, self.corrected)
        self.left_receipt = receive(self.archive, left_v2.raw).receipt_id
        self.right_receipt = receive(self.archive, right_v2.raw).receipt_id
        self.corrected_receipt = receive(self.archive, corrected_v2.raw).receipt_id

    def connect(self, filename):
        db = sqlite3.connect(self.root / filename)
        self.addCleanup(db.close)
        return db

    def assess(self, ids, reading, line=LINE, prior=PRIOR):
        return assess_sum(self.archive, self.reports,
                          AssessmentRequest(ids, prior, line), reading).report.draft

    def test_work_order_table(self):
        cases = (
            ((self.left_receipt, self.right_receipt), 0, Fraction(1), 1, 'isolate'),
            ((self.corrected_receipt, self.right_receipt), 0, Fraction(0), 2, 'release'),
            ((self.left_receipt, self.right_receipt), 1, Fraction(1, 3), 1, 'release'),
            ((self.left_receipt, self.right_receipt), -1, None, None, 'review'),
        )
        for ids, reading, risk, order, disposition in cases:
            with self.subTest(reading=reading):
                draft = self.assess(ids, reading)
                self.assertEqual((draft.status, draft.risk, draft.support_order, draft.disposition),
                                 ('unsupported' if risk is None else 'established',
                                  risk, order, disposition))
                self.assertEqual(draft.sum_reading, Fraction(reading))

    def test_both_stations_point_zero(self):
        left = revise(self.catalog, self.left_revisions, BATCH, "甲", ROWS,
                      parent_id=self.left.revision_id)
        right = revise(self.catalog, self.right_revisions, BATCH, "乙", ROWS,
                       parent_id=self.right.revision_id)
        left_receipt = receive(
            self.archive, issue_sum(self.left_issues, left.revision_id,
                                    POINT_LEFT_SUPPORTS).raw).receipt_id
        right_receipt = receive(
            self.archive, issue_sum(self.right_issues, right.revision_id,
                                    POINT_RIGHT_SUPPORTS).raw).receipt_id
        draft = self.assess((left_receipt, right_receipt), 0)
        self.assertEqual((draft.status, draft.risk, draft.support_order, draft.disposition),
                         ('established', Fraction(0), 0, 'release'))

    def test_isolation_line_boundary(self):
        # Risk 1 at reading 0; line == 1 must still isolate (equality isolates).
        draft = self.assess((self.left_receipt, self.right_receipt), 0, line=1)
        self.assertEqual((draft.risk, draft.disposition), (Fraction(1), 'isolate'))
        below = self.assess((self.left_receipt, self.right_receipt), 0, line='1/1')
        self.assertEqual(below.disposition, 'isolate')

    def test_repeated_redelivery_keeps_receipt(self):
        frozen = issue_sum(self.left_issues, self.left.revision_id, LEFT_SUPPORTS)
        first = receive(self.archive, frozen.raw)
        second = receive(self.archive, frozen.raw)
        self.assertEqual(first.receipt_id, second.receipt_id)
        self.assertEqual(get_received(self.archive, first.receipt_id), first)

    def test_name_swap_alignment(self):
        swapped_names = NAMES[::-1]
        # Canonical exceedance state (A,B_REF)=10 is expressed as 01 in swap order.
        canon_rows = (((0, 0), 1, True, False), ((1, 0), 1, True, True))
        swap_rows = (((0, 0), 1, True, False), ((0, 1), 1, True, True))
        left = revise(self.catalog, self.left_revisions, BATCH, "甲", canon_rows,
                      reference_names=NAMES, parent_id=self.left.revision_id)
        right = revise(self.catalog, self.right_revisions, BATCH, "乙", swap_rows,
                       reference_names=swapped_names, parent_id=self.right.revision_id)
        left_receipt = receive(
            self.archive, issue_sum(self.left_issues, left.revision_id,
                                    ((0, 1), (0, 0))).raw).receipt_id
        right_receipt = receive(
            self.archive, issue_sum(self.right_issues, right.revision_id,
                                    ((0, 1), (0, 1))).raw).receipt_id
        prior_canon = JointPrior(BATCH, make_reference_pair(NAMES), ('1/2', 0, '1/2', 0))
        prior_swap = JointPrior(BATCH, make_reference_pair(swapped_names), ('1/2', '1/2', 0, 0))
        outcomes = []
        for prior in (prior_canon, prior_swap):
            draft = self.assess((left_receipt, right_receipt), 0, prior=prior)
            self.assertEqual(draft.references, NAMES)
            self.assertEqual(draft.prior, (Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(0)))
            outcomes.append((draft.risk, draft.support_order, draft.disposition))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], (Fraction(1), 1, 'isolate'))

    def test_mixed_versions_rejected(self):
        v1 = receive(self.archive, issue(self.left_issues, self.left.revision_id).raw)
        v1_right = receive(self.archive, issue(self.right_issues, self.right.revision_id).raw)
        for request in (
            AssessmentRequest((v1.receipt_id, self.right_receipt), PRIOR, LINE),
            AssessmentRequest((self.left_receipt, v1_right.receipt_id), PRIOR, LINE),
        ):
            with self.subTest(request=request):
                with self.assertRaisesRegex(ValueError, 'V2'):
                    assess_sum(self.archive, self.reports, request, 0)
        with self.assertRaisesRegex(ValueError, 'V1'):
            assess(self.archive, self.reports,
                   AssessmentRequest((self.left_receipt, self.right_receipt), PRIOR, LINE))
        self.assert_no_publication()

    def test_same_station_and_unknown_receipt(self):
        second = receive(
            self.archive, issue_sum(self.left_issues, self.corrected.revision_id,
                                    CORRECTED_SUPPORTS).raw).receipt_id
        with self.assertRaisesRegex(ValueError, 'different stations'):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest((self.left_receipt, second), PRIOR, LINE), 0)
        with self.assertRaises(KeyError):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest((self.left_receipt, 999), PRIOR, LINE), 0)
        self.assert_no_publication()

    def test_invalid_request_inputs(self):
        ids = (self.left_receipt, self.right_receipt)
        bad_prior = JointPrior(BATCH, make_reference_pair(NAMES), (1, 1, 0, 0))
        with self.assertRaises(ValueError):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest(ids, bad_prior, LINE), 0)
        with self.assertRaises(ValueError):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest(ids, PRIOR, '9/8'), 0)
        with self.assertRaises(ValueError):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest(ids, PRIOR, LINE), 'not-a-number')
        # Reference name sets must agree across the two V2 items.
        distributions = [point_state((0, 0), match_atoms=((0, 1),)),
                         point_state((0, 1)), point_state((1, 0)), point_state((1, 1))]
        mismatched = receive(self.archive, pack_sum(
            '乙', distributions, names=('A', 'OTHER'), issue_id=7, revision_id=7))
        with self.assertRaisesRegex(ValueError, 'reference names do not match'):
            assess_sum(self.archive, self.reports,
                       AssessmentRequest((ids[0], mismatched.receipt_id), PRIOR, LINE), 0)
        self.assert_no_publication()

    def test_negative_and_zero_readings_accepted(self):
        # Negative readings are legal inputs; they simply find no support here.
        draft = self.assess((self.left_receipt, self.right_receipt), Fraction(-3, 2))
        self.assertEqual(draft.status, 'unsupported')
        self.assertEqual(draft.sum_reading, Fraction(-3, 2))

    def test_sum_reading_requires_exact_rational(self):
        ids = (self.left_receipt, self.right_receipt)
        for bad_reading in (0.25, True, False):
            with self.subTest(reading=bad_reading):
                with self.assertRaises(ValueError):
                    assess_sum(self.archive, self.reports,
                               AssessmentRequest(ids, PRIOR, LINE), bad_reading)
        # Integer zero and negative exact strings are legitimate.
        ok = assess_sum(self.archive, self.reports,
                        AssessmentRequest(ids, PRIOR, LINE), 0)
        self.assertEqual(ok.report.draft.sum_reading, Fraction(0))
        neg = assess_sum(self.archive, self.reports,
                         AssessmentRequest(ids, PRIOR, LINE), '-1')
        self.assertEqual(neg.report.draft.sum_reading, Fraction(-1))

    def test_reopen_retrieves_sum_report(self):
        bundle = assess_sum(self.archive, self.reports,
                            AssessmentRequest((self.left_receipt, self.right_receipt), PRIOR, LINE), 0)
        report_id = bundle.report.report_id
        with sqlite3.connect(self.root / 'center.sqlite') as reopened:
            reports = ReportStore(reopened)
            reports.initialize()
            recovered = read(reports, report_id)
        self.assertEqual(recovered, bundle)
        draft = recovered.report.draft
        self.assertEqual((draft.sum_reading, draft.support_order), (Fraction(0), 1))
        self.assertEqual(recovered.receipt, bundle.receipt)

    def test_unsupported_publishes_review_and_is_repeatable(self):
        first = assess_sum(self.archive, self.reports,
                           AssessmentRequest((self.left_receipt, self.right_receipt), PRIOR, LINE), -1)
        self.assertEqual(first.report.draft.disposition, 'review')
        second = assess_sum(self.archive, self.reports,
                            AssessmentRequest((self.left_receipt, self.right_receipt), PRIOR, LINE), -1)
        self.assertNotEqual(first.report.report_id, second.report.report_id)

    def test_write_failure_leaves_no_draft_or_receipt(self):
        request = AssessmentRequest((self.left_receipt, self.right_receipt), PRIOR, LINE)
        self.center.execute('''
            CREATE TRIGGER reject_sum_receipt BEFORE INSERT ON sign_receipts
            BEGIN
                SELECT RAISE(ABORT, 'receipt rejected at write');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt rejected at write'):
            assess_sum(self.archive, self.reports, request, 0)
        self.assert_no_publication()
        self.assertFalse(self.center.in_transaction)
        self.center.execute('DROP TRIGGER reject_sum_receipt')
        retried = assess_sum(self.archive, self.reports, request, 0)
        self.assertEqual((retried.report.draft.risk, retried.report.draft.disposition),
                         (Fraction(1), 'isolate'))
        self.assertEqual(read(self.reports, retried.report.report_id), retried)

    def assert_no_publication(self):
        self.assertEqual(self.center.execute('SELECT count(*) FROM signed_reports').fetchone(), (0,))
        self.assertEqual(self.center.execute('SELECT count(*) FROM sign_receipts').fetchone(), (0,))


class SumReceiveValidationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.archive = IntakeArchive(self.db)
        self.archive.initialize()
        uniform_00 = point_state((0, 0), match_intervals=((0, 1, 1),))
        point_11 = point_state((1, 1), match_atoms=((0, 1),), exceed_atoms=((0, 1),))
        empty = (point_state((0, 1)), point_state((1, 0)))
        self.valid = [uniform_00, *empty, point_11]

    def republish(self, mutate, issue_id=50):
        body = json.loads(json.loads(pack_sum('甲', self.valid, issue_id=1))['body'])
        mutate(body)
        body['issue_id'] = issue_id
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'))
        outer = json.loads(pack_sum('甲', self.valid, issue_id=1))
        outer['issue_id'] = issue_id
        outer['body'] = encoded
        outer['sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
        return json.dumps(outer, sort_keys=True, separators=(',', ':')).encode()

    def test_valid_item_accepted(self):
        item = receive(self.archive, pack_sum('甲', self.valid))
        self.assertEqual(item.envelope.version, 2)

    def test_domination_violations_rejected(self):
        def point_overflow(body):
            body['distributions'][3]['exceed']['components'].append(['0', '999'])

        def density_overflow(body):
            body['distributions'][0]['match']['components'] = [['0', '1', '1']]
            body['distributions'][0]['exceed']['components'] = [['0', '1', '2']]

        def partial_overflow(body):
            body['distributions'][0]['match']['components'] = [['0', '1', '1']]
            body['distributions'][0]['exceed']['components'] = [['0', '2', '2']]

        for mutate in (point_overflow, density_overflow, partial_overflow):
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaises(ValueError):
                    receive(self.archive, self.republish(mutate))
        self.assertEqual(self.db.execute('SELECT count(*) FROM received_items').fetchone(), (0,))

    def test_malformed_components_rejected(self):
        def zero_width_interval(body):
            body['distributions'][0]['match']['components'] = [['0', '0', '1']]

        def negative_mass(body):
            body['distributions'][0]['match']['components'] = [['0', '-1']]

        def missing_state(body):
            body['distributions'].pop()

        def duplicate_state(body):
            body['distributions'][1]['state'] = [0, 0]

        for mutate in (zero_width_interval, negative_mass, missing_state, duplicate_state):
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaises(ValueError):
                    receive(self.archive, self.republish(mutate))

    def test_identity_conflict_and_bad_digest(self):
        raw = pack_sum('甲', self.valid)
        receive(self.archive, raw)
        changed = json.loads(raw)
        changed['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            receive(self.archive, json.dumps(changed).encode())
        # Same identity but a different body must be rejected without a new receipt.
        body = json.loads(json.loads(raw)['body'])
        body['distributions'][0]['match']['components'] = [['0', '1', '2']]
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'))
        conflict = json.loads(raw)
        conflict['body'] = encoded
        conflict['sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'identity'):
            receive(self.archive, json.dumps(conflict).encode())
        self.assertEqual(self.db.execute('SELECT count(*) FROM received_items').fetchone(), (1,))

    def test_duplicate_json_key_rejected(self):
        raw = pack_sum('甲', self.valid).decode()
        duplicated = raw.replace('"version":2', '"version":2,"version":2', 1)
        with self.assertRaises(ValueError):
            receive(self.archive, duplicated.encode())


if __name__ == '__main__':
    unittest.main()
