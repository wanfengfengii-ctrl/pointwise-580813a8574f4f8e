from dataclasses import dataclass

from batch.policy import IsolationLine, RationalInput, exact_fraction
from batch.priors import JointPrior
from intake.archive import IntakeArchive
from report.publish import publish
from report.records import make_draft, make_sum_draft
from report.retrieve import ReportBundle
from report.store import ReportStore
from .context import bind_context
from .disposition import decide
from .evaluate import evaluate
from .sum_context import bind_sum_context
from .sum_evaluate import SumRiskStatus, evaluate_sum


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


def _decide_sum(result, isolation_line: IsolationLine):
    from .disposition import Disposition
    if result.status == SumRiskStatus.UNSUPPORTED:
        return Disposition.REVIEW
    if result.risk is None:
        raise ValueError('established sum risk must have a numeric value')
    if result.risk >= isolation_line.value:
        return Disposition.ISOLATE
    return Disposition.RELEASE


def assess_sum(archive: IntakeArchive, reports: ReportStore, request: AssessmentRequest,
               sum_reading: RationalInput) -> ReportBundle:
    reading = exact_fraction(sum_reading, 'sum reading')
    context = bind_sum_context(archive, request.receipt_ids, request.prior,
                               request.isolation_line, reading)
    result = evaluate_sum(context)
    disposition = _decide_sum(result, context.isolation_line)
    return publish(reports, make_sum_draft(context, result, disposition))
