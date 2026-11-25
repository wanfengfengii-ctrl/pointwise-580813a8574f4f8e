import argparse
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile

from batch import BatchStore, JointPrior, make_reference_pair, register
from intake import IntakeArchive, receive
from report import ReportStore, read
from risk import AssessmentRequest, assess, assess_sum
from station import IssueStore, RevisionStore, issue, issue_sum, revise

BATCH = 'FILM-01'
SUM_BATCH = 'FILM-SUM'
NAMES = ('A', 'B_REF')
UNIFORM = ('1/4', '1/4', '1/4', '1/4')
SKEW = ('1/4', '0', '0', '3/4')
LEFT_ROWS = (((0, 0), '1', True, False), ((1, 1), '1', True, True))
RIGHT_ROWS = (((0, 0), '1', True, False), ((1, 1), '1/2', True, True))
CORRECTION_ROWS = (((0, 1), '1', True, False), ((1, 0), '1', True, True))

# Sum-reading handoff: both stations carry weight 1 in 00 and 11, only 11 exceeds.
SUM_ROWS = (((0, 0), 1, True, False), ((1, 1), 1, True, True))
SUM_PRIOR = ('1/2', '0', '0', '1/2')
SUM_LINE = '3/4'
LEFT_SUPPORTS = ((0, 1), (0, 0))
RIGHT_SUPPORTS = ((0, 1), (0, 1))
CORRECTED_SUPPORTS = ((0, 1), (2, 2))
POINT_LEFT_SUPPORTS = ((0, 0), (0, 0))
POINT_RIGHT_SUPPORTS = ((0, 0), (0, 1))


@contextmanager
def sample_issues(directory: Path, batch_id: str = BATCH):
    with (closing(sqlite3.connect(directory / 'catalog.sqlite')) as catalog_db,
          closing(sqlite3.connect(directory / 'station-a.sqlite')) as left_db,
          closing(sqlite3.connect(directory / 'station-b.sqlite')) as right_db):
        catalog = BatchStore(catalog_db)
        catalog.initialize()
        register(catalog, batch_id, NAMES, '1/4')
        left_revisions, right_revisions = RevisionStore(left_db), RevisionStore(right_db)
        left_issues, right_issues = IssueStore(left_db), IssueStore(right_db)
        for store in (left_revisions, right_revisions, left_issues, right_issues):
            store.initialize()
        left = revise(catalog, left_revisions, batch_id, '甲', LEFT_ROWS)
        right = revise(catalog, right_revisions, batch_id, '乙', RIGHT_ROWS)
        first_left = issue(left_issues, left.revision_id)
        first_right = issue(right_issues, right.revision_id)
        correction = revise(catalog, left_revisions, batch_id, '甲', CORRECTION_ROWS,
                            parent_id=left.revision_id)
        yield first_left, first_right, issue(left_issues, correction.revision_id)


def request(batch_id, ids, masses=UNIFORM, line='1/4'):
    return AssessmentRequest(ids, JointPrior(batch_id, make_reference_pair(NAMES), masses), line)


@contextmanager
def sum_sample_issues(directory: Path, batch_id: str = SUM_BATCH):
    """Issue V1 and V2 fixed items for the sum-reading night shift, then close stations."""
    with (closing(sqlite3.connect(directory / 'sum-catalog.sqlite')) as catalog_db,
          closing(sqlite3.connect(directory / 'sum-station-a.sqlite')) as left_db,
          closing(sqlite3.connect(directory / 'sum-station-b.sqlite')) as right_db):
        catalog = BatchStore(catalog_db)
        catalog.initialize()
        register(catalog, batch_id, NAMES, SUM_LINE)
        left_revisions, right_revisions = RevisionStore(left_db), RevisionStore(right_db)
        left_issues, right_issues = IssueStore(left_db), IssueStore(right_db)
        for store in (left_revisions, right_revisions, left_issues, right_issues):
            store.initialize()
        left = revise(catalog, left_revisions, batch_id, '甲', SUM_ROWS)
        right = revise(catalog, right_revisions, batch_id, '乙', SUM_ROWS)
        corrected = revise(catalog, left_revisions, batch_id, '甲', SUM_ROWS,
                           parent_id=left.revision_id)
        point_left = revise(catalog, left_revisions, batch_id, '甲', SUM_ROWS,
                            parent_id=corrected.revision_id)
        point_right = revise(catalog, right_revisions, batch_id, '乙', SUM_ROWS,
                             parent_id=right.revision_id)
        yield {
            'original': (
                issue_sum(left_issues, left.revision_id, LEFT_SUPPORTS),
                issue_sum(right_issues, right.revision_id, RIGHT_SUPPORTS),
            ),
            'corrected': (
                issue_sum(left_issues, corrected.revision_id, CORRECTED_SUPPORTS),
                issue_sum(right_issues, right.revision_id, RIGHT_SUPPORTS),
            ),
            'point_zero': (
                issue_sum(left_issues, point_left.revision_id, POINT_LEFT_SUPPORTS),
                issue_sum(right_issues, point_right.revision_id, POINT_RIGHT_SUPPORTS),
            ),
        }


def _outcome(bundle):
    draft = bundle.report.draft
    return {'status': draft.status, 'risk': None if draft.risk is None else str(draft.risk)}


def _decision(bundle):
    return {
        'disposition': bundle.report.draft.disposition,
        'receipt_ids': [source.receipt_id for source in bundle.report.draft.sources],
        'receipt_matches_report': bundle.receipt.report_id == bundle.report.report_id,
    }


def _observe(case_id, inputs, expected, bundle, downstream_expected, paths, oracle):
    record = {
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': _outcome(bundle),
        'downstream_expected': downstream_expected,
        'downstream_actual': _decision(bundle),
        'code_paths': paths,
        'oracle': oracle,
    }
    if record['actual'] != expected or record['downstream_actual'] != downstream_expected:
        print('BATCH_RISK_MISMATCH ' + json.dumps(record, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


def _sum_outcome(bundle):
    draft = bundle.report.draft
    return {
        'status': draft.status,
        'risk': None if draft.risk is None else str(draft.risk),
        'support_order': draft.support_order,
        'disposition': draft.disposition,
        'sum_reading': str(draft.sum_reading),
    }


def run_sum(archive, reports, directory: Path, batch_id: str) -> list:
    """Exercise the post-closure V2 sum-reading rulings and return their report ids."""
    sum_paths = ['station/distribution.py', 'station/sum_issue.py', 'intake/sum_validate.py',
                 'risk/neighborhood.py', 'risk/sum_evaluate.py', 'risk/request.py']
    report_ids = []
    with sum_sample_issues(directory, batch_id) as items:
        receipts = {
            name: (receive(archive, left.raw).receipt_id, receive(archive, right.raw).receipt_id)
            for name, (left, right) in items.items()
        }
    # Stations are now closed; the center decides only from the archived fixed items.
    scenarios = (
        ('sum-original-0', 'original', 0,
         {'status': 'established', 'risk': '1', 'support_order': 1,
          'disposition': 'isolate', 'sum_reading': '0'},
         'The 11 atom+interval boundary contributes order one; both exceed, so the limit is 1.'),
        ('sum-corrected-0', 'corrected', 0,
         {'status': 'established', 'risk': '0', 'support_order': 2,
          'disposition': 'release', 'sum_reading': '0'},
         'Moving the 11 point to 2 leaves only the 00 interval+interval tip, an order-two term.'),
        ('sum-original-1', 'original', 1,
         {'status': 'established', 'risk': '1/3', 'support_order': 1,
          'disposition': 'release', 'sum_reading': '1'},
         'The 00 trapezoid center and the 11 boundary share order one; the limit is 1/3.'),
        ('sum-original-neg1', 'original', -1,
         {'status': 'unsupported', 'risk': None, 'support_order': None,
          'disposition': 'review', 'sum_reading': '-1'},
         'No convolution reaches -1 in any positive neighborhood, so the case waits for review.'),
        ('sum-point-zero', 'point_zero', 0,
         {'status': 'established', 'risk': '0', 'support_order': 0,
          'disposition': 'release', 'sum_reading': '0'},
         'Both 00 readings are point masses at zero, giving a zero-order atom-atom denominator.'),
    )
    for case_id, key, reading, expected, oracle in scenarios:
        ids = receipts[key]
        bundle = assess_sum(
            archive, reports,
            AssessmentRequest(ids, JointPrior(batch_id, make_reference_pair(NAMES), SUM_PRIOR),
                              SUM_LINE),
            reading)
        actual = _sum_outcome(bundle)
        record = {'case_id': case_id, 'receipt_ids': list(ids), 'expected': expected,
                  'actual': actual, 'code_paths': sum_paths, 'oracle': oracle}
        if actual != expected:
            print('BATCH_SUM_MISMATCH ' + json.dumps(record, ensure_ascii=False, sort_keys=True))
            raise SystemExit(1)
        print('POINTWISE_SUM_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))
        report_ids.append(bundle.report.report_id)
    return report_ids


def run(directory: Path, batch_id: str) -> None:
    center = directory / 'center.sqlite'
    paths = ['station/evidence.py', 'station/issue.py', 'intake/receipt.py', 'risk/context.py',
             'risk/evaluate.py', 'risk/disposition.py', 'report/store.py']
    with closing(sqlite3.connect(center)) as db:
        archive, reports = IntakeArchive(db), ReportStore(db)
        archive.initialize()
        reports.initialize()
        with sample_issues(directory, batch_id) as (first_left, first_right, correction):
            left = receive(archive, first_left.raw)
            right = receive(archive, first_right.raw)
        ids = (left.receipt_id, right.receipt_id)
        old = assess(archive, reports, request(batch_id, ids))
        old_number = old.report.report_id
        inputs = {'batch_id': batch_id, 'references': NAMES, 'left_rows': LEFT_ROWS,
                  'right_rows': RIGHT_ROWS, 'receipt_ids': ids}
        isolated = {'disposition': 'isolate', 'receipt_ids': list(ids), 'receipt_matches_report': True}
        _observe('v4', {**inputs, 'prior': UNIFORM, 'line': '1/4'},
                 {'status': 'established', 'risk': '1/3'}, old, isolated, paths,
                 '00 contributes 1/4 to D and 11 contributes 1/8 to D and N. 1/8 divided by 3/8 is 1/3.')
        skewed = assess(archive, reports, request(batch_id, ids, SKEW, '3/5'))
        _observe('v9', {**inputs, 'prior': SKEW, 'line': '3/5'},
                 {'status': 'established', 'risk': '3/5'}, skewed, isolated, paths,
                 'D is 1/4 plus 3/8 and N is 3/8. The quotient equals the isolation line.')
        revised = receive(archive, correction.raw)
        revised_ids = (revised.receipt_id, right.receipt_id)
        new = assess(archive, reports, request(batch_id, revised_ids))
        _observe('v5', {**inputs, 'left_rows': CORRECTION_ROWS, 'receipt_ids': revised_ids,
                        'prior': UNIFORM, 'line': '1/4'},
                 {'status': 'incompatible', 'risk': None}, new,
                 {'disposition': 'review', 'receipt_ids': list(revised_ids), 'receipt_matches_report': True},
                 paths, 'The corrected left supports 01 and 10. The right supports 00 and 11.')
    with closing(sqlite3.connect(center)) as reopened:
        archive = IntakeArchive(reopened)
        reports = ReportStore(reopened)
        archive.initialize()
        reports.initialize()
        recovered = read(reports, old_number)
        if recovered != old:
            raise RuntimeError(f'original report {old_number} was not recovered intact')
        _observe('v8', {'old_number': old_number, 'correction_receipt': revised.receipt_id},
                 {'status': 'established', 'risk': '1/3'}, recovered, isolated,
                 ['report/records.py', 'report/receipts.py', 'report/store.py', 'report/retrieve.py'],
                 'The reopened bundle equals the original signed snapshot and its original receipt.')
        # The sum handoff runs after the stations have closed, purely from fixed items.
        sum_report_ids = run_sum(archive, reports, directory, batch_id + '-SUM')
    with closing(sqlite3.connect(center)) as reopened:
        store = ReportStore(reopened)
        store.initialize()
        for report_id in sum_report_ids:
            recovered_sum = read(store, report_id)
            if recovered_sum is None or recovered_sum.report.report_id != report_id:
                raise RuntimeError(f'sum report {report_id} was not recovered intact')
            print('POINTWISE_SUM_REOPEN ' + json.dumps({
                'report_id': report_id,
                'sum_reading': str(recovered_sum.report.draft.sum_reading),
                'support_order': recovered_sum.report.draft.support_order,
                'receipt_number': recovered_sum.receipt.receipt_number,
            }, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description='启衡材料老化复验工作日演示')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--batch', default=BATCH)
    args = parser.parse_args()
    try:
        if args.directory is None:
            with tempfile.TemporaryDirectory(prefix='film-review-') as temp:
                run(Path(temp), args.batch)
        else:
            args.directory.mkdir(parents=True, exist_ok=True)
            run(args.directory, args.batch)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(status=1, message=f'{exc}\n')


if __name__ == '__main__':
    main()
