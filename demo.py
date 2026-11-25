import argparse
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile

from batch import BatchStore, JointPrior, make_reference_pair, register
from intake import IntakeArchive, receive
from report import ReportStore, read
from risk import AssessmentRequest, assess
from station import IssueStore, RevisionStore, issue, revise

BATCH = 'FILM-01'
NAMES = ('A', 'B_REF')
UNIFORM = ('1/4', '1/4', '1/4', '1/4')
SKEW = ('1/4', '0', '0', '3/4')
LEFT_ROWS = (((0, 0), '1', True, False), ((1, 1), '1', True, True))
RIGHT_ROWS = (((0, 0), '1', True, False), ((1, 1), '1/2', True, True))
CORRECTION_ROWS = (((0, 1), '1', True, False), ((1, 0), '1', True, True))


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
        store = ReportStore(reopened)
        store.initialize()
        recovered = read(store, old_number)
        if recovered != old:
            raise RuntimeError(f'original report {old_number} was not recovered intact')
        _observe('v8', {'old_number': old_number, 'correction_receipt': revised.receipt_id},
                 {'status': 'established', 'risk': '1/3'}, recovered, isolated,
                 ['report/records.py', 'report/receipts.py', 'report/store.py', 'report/retrieve.py'],
                 'The reopened bundle equals the original signed snapshot and its original receipt.')


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
