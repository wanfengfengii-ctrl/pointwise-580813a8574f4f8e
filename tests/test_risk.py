from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from batch import JointPrior, make_reference_pair
from demo import BATCH, NAMES, SKEW, UNIFORM, request, sample_issues
from intake import IntakeArchive, receive
from report import ReportStore
from risk import AssessmentRequest, assess

LEFT = ((1, 0), (0, 0), (0, 0), (1, 1))
RIGHT = ((1, 0), (0, 0), (0, 0), ('1/2', '1/2'))
CORRECTED = ((0, 0), (1, 0), (1, 1), (0, 0))


def pack_complete(station, weights, *, batch_id=BATCH, names=NAMES, issue_id=1, revision_id=1,
                  state_order=((0, 0), (0, 1), (1, 0), (1, 1))):
    """Write an interchange fixture from literal masses without a station or its encoder."""
    identity = dict(batch_id=batch_id, station=station, revision_id=revision_id, issue_id=issue_id)
    evidence = [dict(state=list(state), likelihood=str(likelihood), exceedance=str(exceedance))
                for state, (likelihood, exceedance) in zip(state_order, weights, strict=True)]
    body = json.dumps(dict(identity, references=list(names), evidence=evidence), ensure_ascii=False)
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    return json.dumps(dict(identity, version=1, body=body, sha256=digest), ensure_ascii=False).encode('utf-8')


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.archive, self.reports = IntakeArchive(self.db), ReportStore(self.db)
        self.archive.initialize()
        self.reports.initialize()

    def received(self, station, weights, **fields):
        return receive(self.archive, pack_complete(station, weights, **fields)).receipt_id

    def pair(self):
        return self.received('甲', LEFT), self.received('乙', RIGHT)

    def evaluate_request(self, ids, masses=UNIFORM, line='1/4'):
        return assess(self.archive, self.reports, request(BATCH, ids, masses, line))

    def assert_outcome(self, bundle, risk, status, disposition, ids):
        draft = bundle.report.draft
        self.assertEqual((draft.risk, draft.status, draft.disposition), (risk, status, disposition))
        self.assertEqual(tuple(source.receipt_id for source in draft.sources), ids)
        self.assertEqual(bundle.report.report_id, bundle.receipt.report_id)

    def assert_no_publication(self):
        self.assertEqual(self.db.execute('SELECT count(*) FROM signed_reports').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM sign_receipts').fetchone(), (0,))

    def test_joint_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with sample_issues(path) as (a, b, _):
                left = receive(self.archive, a.raw)
                right = receive(self.archive, b.raw)
            # Make the source paths unavailable before the actual analysis.
            for filename in ('catalog.sqlite', 'station-a.sqlite', 'station-b.sqlite'):
                (path / filename).rename(path / (filename + '.closed'))
            ids = (left.receipt_id, right.receipt_id)
            result = self.evaluate_request(ids)
            self.assert_outcome(result, Fraction(1, 3), 'established', 'isolate', ids)
            self.assertEqual([source.digest for source in result.report.draft.sources],
                             [left.envelope.digest, right.envelope.digest])

    def test_complete_fixture(self):
        ids = self.pair()
        newer = self.received('甲', CORRECTED, issue_id=2, revision_id=2)
        self.assert_outcome(self.evaluate_request(ids), Fraction(1, 3), 'established', 'isolate', ids)
        changed = (newer, ids[1])
        self.assert_outcome(self.evaluate_request(changed), None, 'incompatible', 'review', changed)

    def test_named_alignment(self):
        left = self.received('甲', [(1, 0), (1, 1), (0, 0), (0, 0)])
        right = self.received('乙', [('1/2', '1/2'), (0, 0), (1, 0), (0, 0)],
                              names=NAMES[::-1], state_order=((1, 0), (0, 1), (0, 0), (1, 1)))
        prior = JointPrior(BATCH, make_reference_pair(NAMES[::-1]), ('1/4', 0, '3/4', 0))
        for ids in ((left, right), (right, left)):
            bundle = assess(self.archive, self.reports, AssessmentRequest(ids, prior, '3/5'))
            self.assert_outcome(bundle, Fraction(3, 5), 'established', 'isolate', ids)
            self.assertEqual(bundle.report.draft.references, NAMES)
            self.assertEqual(bundle.report.draft.prior, (Fraction(1, 4), Fraction(3, 4), 0, 0))

    def test_support_and_zero(self):
        left, right = self.pair()
        corrected = self.received('甲', CORRECTED, issue_id=2, revision_id=2)
        quiet = self.received('乙', [(1, 0), (0, 0), (0, 0), ('1/2', 0)], issue_id=2, revision_id=2)
        disjoint = (corrected, right)
        self.assert_outcome(self.evaluate_request(disjoint), None, 'incompatible', 'review', disjoint)
        common = (left, quiet)
        self.assert_outcome(self.evaluate_request(common), Fraction(0), 'established', 'release', common)
        self.assert_outcome(self.evaluate_request(common, line=0), Fraction(0), 'established', 'isolate', common)

    def test_zero_prior_support(self):
        ids = self.pair()
        result = self.evaluate_request(ids, (0, 1, 0, 0))
        self.assert_outcome(result, None, 'incompatible', 'review', ids)

    def test_cross_batch(self):
        left = self.received('甲', LEFT)
        right = self.received('乙', RIGHT, batch_id='OTHER')
        with self.assertRaisesRegex(ValueError, 'different batches'):
            self.evaluate_request((left, right))
        self.assert_no_publication()

    def test_invalid_request(self):
        left, right = self.pair()
        duplicate = self.received('甲', LEFT, issue_id=2, revision_id=2)
        mismatched = self.received('乙', RIGHT, names=('A', 'OTHER'), issue_id=2, revision_id=2)
        invalid_requests = [
            (request(BATCH, (left, 999)), KeyError),
            (request(BATCH, (left, duplicate)), ValueError),
            (request(BATCH, (left, mismatched)), ValueError),
            (request('OTHER', (left, right)), ValueError),
            (request(BATCH, (left, right), (1, 1, 0, 0)), ValueError),
            (request(BATCH, (left, right), (2, -1, 0, 0)), ValueError),
            (request(BATCH, (left, right), (1, 0, 0)), ValueError),
            (request(BATCH, (left, right), (True, 0, 0, 0)), ValueError),
            (request(BATCH, (left, right), line='9/8'), ValueError),
            (request(BATCH, (left, right), line=0.25), ValueError),
            (AssessmentRequest((left, right), JointPrior(BATCH, make_reference_pair(('A', 'X')),
                                                         UNIFORM), '1/4'), ValueError),
        ]
        for candidate, error in invalid_requests:
            with self.subTest(request=candidate):
                with self.assertRaises(error):
                    assess(self.archive, self.reports, candidate)
                self.assert_no_publication()
        self.assert_outcome(self.evaluate_request((left, right)), Fraction(1, 3),
                            'established', 'isolate', (left, right))

    def test_invalid_evidence(self):
        left = self.received('甲', LEFT)
        invalid_cases = (
            ([(1, 2), *RIGHT[1:]], ((0, 0), (0, 1), (1, 0), (1, 1))),
            ([(-1, 0), *RIGHT[1:]], ((0, 0), (0, 1), (1, 0), (1, 1))),
            (RIGHT, ((0, 0), (0, 1), (0, 1), (1, 1))),
            (RIGHT[:3], ((0, 0), (0, 1), (1, 0))),
        )
        for issue_id, (weights, states) in enumerate(invalid_cases, start=1):
            with self.subTest(issue_id=issue_id):
                right = self.received('乙', weights, issue_id=issue_id, revision_id=issue_id,
                                      state_order=states)
                with self.assertRaises(ValueError):
                    self.evaluate_request((left, right))
                self.assert_no_publication()

    def test_nonuniform_prior(self):
        ids = self.pair()
        uniform = self.evaluate_request(ids)
        skewed = self.evaluate_request(ids, SKEW, '3/5')
        self.assert_outcome(uniform, Fraction(1, 3), 'established', 'isolate', ids)
        self.assert_outcome(skewed, Fraction(3, 5), 'established', 'isolate', ids)
        self.assertEqual(skewed.report.draft.isolation_line, Fraction(3, 5))
        above = self.evaluate_request(ids, SKEW, '2/3')
        self.assert_outcome(above, Fraction(3, 5), 'established', 'release', ids)

    def test_station_scale(self):
        left, right = self.pair()
        scale = Fraction(7, 3)
        scaled = self.received('甲', [(scale * l, scale * h) for l, h in LEFT],
                               issue_id=2, revision_id=2)
        for ids in ((left, right), (scaled, right)):
            result = self.evaluate_request(ids, SKEW, '3/5')
            self.assert_outcome(result, Fraction(3, 5), 'established', 'isolate', ids)
