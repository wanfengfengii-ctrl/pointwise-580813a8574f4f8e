"""Sum-reading risk evaluation across the four named states."""
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from .neighborhood import convolution_coefficients
from .sum_context import SumAssessmentContext


class SumRiskStatus(StrEnum):
    ESTABLISHED = 'established'
    UNSUPPORTED = 'unsupported'


@dataclass(frozen=True)
class SumRiskResult:
    status: SumRiskStatus
    risk: Fraction | None
    support_order: int | None


def evaluate_sum(context: SumAssessmentContext) -> SumRiskResult:
    # Accumulate the neighborhood polynomial coefficients per order over every
    # state.  Each state's joint contribution is multiplied by its single prior,
    # so the shared prior is counted exactly once even though two stations meet.
    denominator: dict[int, Fraction] = {}
    numerator: dict[int, Fraction] = {}
    for prior, left, right in zip(context.prior.masses, context.left, context.right, strict=True):
        if prior == 0:
            continue
        for order, coefficient in convolution_coefficients(
                context.sum_reading, left.match, right.match).items():
            denominator[order] = denominator.get(order, Fraction(0)) + prior * coefficient
        for order, coefficient in convolution_coefficients(
                context.sum_reading, left.exceed, right.exceed).items():
            numerator[order] = numerator.get(order, Fraction(0)) + prior * coefficient
    positive_orders = [order for order, value in denominator.items() if value > 0]
    if not positive_orders:
        return SumRiskResult(SumRiskStatus.UNSUPPORTED, None, None)
    support_order = min(positive_orders)
    risk = numerator.get(support_order, Fraction(0)) / denominator[support_order]
    return SumRiskResult(SumRiskStatus.ESTABLISHED, risk, support_order)
