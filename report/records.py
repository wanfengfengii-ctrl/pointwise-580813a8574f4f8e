from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from risk.context import AssessmentContext
    from risk.disposition import Disposition
    from risk.evaluate import RiskResult


@dataclass(frozen=True)
class ReportSource:
    receipt_id: int
    batch_id: str
    station: str
    revision_id: int
    issue_id: int
    digest: str


@dataclass(frozen=True)
class ReportDraft:
    batch_id: str
    references: tuple[str, str]
    sources: tuple[ReportSource, ReportSource]
    prior: tuple[Fraction, ...]
    isolation_line: Fraction
    status: str
    risk: Fraction | None
    disposition: str


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    draft: ReportDraft


def make_draft(context: AssessmentContext, result: RiskResult, disposition: Disposition) -> ReportDraft:
    sources = tuple(
        ReportSource(item.receipt_id, *item.envelope.identity, item.envelope.digest)
        for item in context.items
    )
    return ReportDraft(context.batch_id, context.references.names, sources, context.prior.masses,
                       context.isolation_line.value, result.status.value, result.risk, disposition.value)


def encode_report(draft: ReportDraft) -> str:
    return json.dumps({
        'batch_id': draft.batch_id,
        'references': draft.references,
        'sources': [asdict(source) for source in draft.sources],
        'prior': [str(mass) for mass in draft.prior],
        'isolation_line': str(draft.isolation_line),
        'status': draft.status,
        'risk': None if draft.risk is None else str(draft.risk),
        'disposition': draft.disposition,
    }, sort_keys=True, separators=(',', ':'))


def restore_report(report_id: int, encoded: str) -> SignedReport:
    fields = json.loads(encoded)
    risk = fields['risk']
    draft = ReportDraft(
        batch_id=fields['batch_id'],
        references=tuple(fields['references']),
        sources=tuple(ReportSource(**source) for source in fields['sources']),
        prior=tuple(Fraction(mass) for mass in fields['prior']),
        isolation_line=Fraction(fields['isolation_line']),
        status=fields['status'],
        risk=None if risk is None else Fraction(risk),
        disposition=fields['disposition'],
    )
    return SignedReport(report_id, draft)
