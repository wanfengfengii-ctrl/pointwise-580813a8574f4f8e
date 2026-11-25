from enum import StrEnum

from batch.policy import IsolationLine
from .evaluate import RiskResult, RiskStatus


class Disposition(StrEnum):
    ISOLATE = 'isolate'
    RELEASE = 'release'
    REVIEW = 'review'


def decide(result: RiskResult, isolation_line: IsolationLine) -> Disposition:
    if result.status == RiskStatus.INCOMPATIBLE:
        return Disposition.REVIEW
    if result.risk is None:
        raise ValueError('established risk must have a numeric value')
    if result.risk >= isolation_line.value:
        return Disposition.ISOLATE
    return Disposition.RELEASE
