"""Source data for the sum-reading handoff and a V1 comparison."""
from contextlib import closing
from fractions import Fraction
import json
import sqlite3

from batch import BatchStore, JointPrior, make_reference_pair, register
from intake import IntakeArchive, receive
from report import ReportStore
from risk import AssessmentRequest, assess
from station import IssueStore, RevisionStore, issue, issue_sum, revise

BATCH = "FILM-SUM"
NAMES = ("A", "B_REF")
LINE = "3/4"
PRIOR = JointPrior(BATCH, make_reference_pair(NAMES), ("1/2", 0, 0, "1/2"))
ROWS = (((0, 0), 1, True, False), ((1, 1), 1, True, True))
LEFT_SUPPORTS = ((0, 1), (0, 0))
RIGHT_SUPPORTS = ((0, 1), (0, 1))
CORRECTED_SUPPORTS = ((0, 1), (2, 2))
# Fifth work-order case: both stations reduce the 00 reading to a point at zero.
POINT_LEFT_SUPPORTS = ((0, 0), (0, 0))
POINT_RIGHT_SUPPORTS = ((0, 0), (0, 1))


def source_fixture(catalog, left_revisions, right_revisions):
    """Return the left original, right original and left correction."""
    register(catalog, BATCH, NAMES, LINE)
    left = revise(catalog, left_revisions, BATCH, "甲", ROWS)
    right = revise(catalog, right_revisions, BATCH, "乙", ROWS)
    corrected = revise(catalog, left_revisions, BATCH, "甲", ROWS, parent_id=left.revision_id)
    return left, right, corrected


def issue_sum_fixture(left_issues, right_issues, left, right, corrected):
    """Issue the V2 fixed items for the three FILM-SUM revisions."""
    left_v2 = issue_sum(left_issues, left.revision_id, LEFT_SUPPORTS)
    right_v2 = issue_sum(right_issues, right.revision_id, RIGHT_SUPPORTS)
    corrected_v2 = issue_sum(left_issues, corrected.revision_id, CORRECTED_SUPPORTS)
    return left_v2, right_v2, corrected_v2


# (label, which left V2, which right V2, sum reading, risk, support_order, disposition)
WORK_ORDER = (
    ("original pair at 0", "original", "original", 0, Fraction(1), 1, "isolate"),
    ("corrected left at 0", "corrected", "original", 0, Fraction(0), 2, "release"),
    ("original pair at 1", "original", "original", 1, Fraction(1, 3), 1, "release"),
    ("original pair at -1", "original", "original", -1, None, None, "review"),
)


def main():
    with closing(sqlite3.connect(":memory:")) as center:
        archive, reports = IntakeArchive(center), ReportStore(center)
        archive.initialize()
        reports.initialize()
        with (closing(sqlite3.connect(":memory:")) as catalog_db,
              closing(sqlite3.connect(":memory:")) as left_db,
              closing(sqlite3.connect(":memory:")) as right_db):
            catalog = BatchStore(catalog_db)
            left_revisions, right_revisions = RevisionStore(left_db), RevisionStore(right_db)
            left_issues, right_issues = IssueStore(left_db), IssueStore(right_db)
            for store in (catalog, left_revisions, right_revisions, left_issues, right_issues):
                store.initialize()
            left, right, corrected = source_fixture(catalog, left_revisions, right_revisions)
            a = receive(archive, issue(left_issues, left.revision_id).raw)
            b = receive(archive, issue(right_issues, right.revision_id).raw)
            a2 = receive(archive, issue(left_issues, corrected.revision_id).raw)

        if a.receipt_id == a2.receipt_id:
            raise AssertionError("the correction needs its own receipt")
        if json.loads(a.envelope.body)["evidence"] != json.loads(a2.envelope.body)["evidence"]:
            raise AssertionError("the V1 summaries should coincide")
        for name, item in (("original", a), ("corrected", a2)):
            ids = (item.receipt_id, b.receipt_id)
            result = assess(archive, reports, AssessmentRequest(ids, PRIOR, LINE))
            draft = result.report.draft
            if (draft.risk, draft.disposition) != (Fraction(1, 2), "release"):
                raise AssertionError(f"unexpected V1 decision for {name}: {draft}")
            print(json.dumps({"case": name, "version": 1, "receipt_ids": ids,
                              "risk": str(draft.risk), "disposition": draft.disposition},
                             ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
