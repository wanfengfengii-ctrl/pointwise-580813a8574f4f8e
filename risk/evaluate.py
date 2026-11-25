from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from .context import AssessmentContext


class RiskStatus(StrEnum):
    ESTABLISHED = 'established'
    INCOMPATIBLE = 'incompatible'


@dataclass(frozen=True)
class RiskResult:
    status: RiskStatus
    risk: Fraction | None


def evaluate(context: AssessmentContext) -> RiskResult:
    common = Fraction(0)
    both_exceed = Fraction(0)
    for prior, left, right in zip(context.prior.masses, context.left, context.right, strict=True):
        common += prior * left.likelihood * right.likelihood
        both_exceed += prior * left.exceedance * right.exceedance
    if common == 0:
        return RiskResult(RiskStatus.INCOMPATIBLE, None)
    return RiskResult(RiskStatus.ESTABLISHED, both_exceed / common)
