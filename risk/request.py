from dataclasses import dataclass

from batch.policy import IsolationLine, RationalInput
from batch.priors import JointPrior
from intake.archive import IntakeArchive
from report.publish import publish
from report.records import make_draft
from report.retrieve import ReportBundle
from report.store import ReportStore
from .context import bind_context
from .disposition import decide
from .evaluate import evaluate


@dataclass(frozen=True)
class AssessmentRequest:
    receipt_ids: tuple[int, int]
    prior: JointPrior
    isolation_line: RationalInput | IsolationLine


def assess(archive: IntakeArchive, reports: ReportStore, request: AssessmentRequest) -> ReportBundle:
    context = bind_context(archive, request.receipt_ids, request.prior, request.isolation_line)
    result = evaluate(context)
    disposition = decide(result, context.isolation_line)
    return publish(reports, make_draft(context, result, disposition))
