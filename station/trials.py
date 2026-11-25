from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from batch.policy import exact_fraction
from batch.references import JointState, ReferencePair, validate_state


@dataclass(frozen=True)
class TrialRecord:
    state: JointState
    weight: Fraction
    matches: bool
    exceeds: bool


@dataclass(frozen=True)
class TrialSet:
    references: ReferencePair
    rows: tuple[TrialRecord, ...]


def validate_trials(references: ReferencePair, rows: Iterable) -> TrialSet:
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError('trial rows must be iterable') from exc
    records = []
    for index, row in enumerate(iterator, start=1):
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise ValueError(f'trial {index} needs state, weight, match and exceedance')
        state, weight_value, matches, exceeds = row
        state = validate_state(state)
        weight = exact_fraction(weight_value, f'trial {index} weight')
        if weight < 0:
            raise ValueError(f'trial {index} weight must be nonnegative')
        if type(matches) is not bool or type(exceeds) is not bool:
            raise ValueError(f'trial {index} flags must be boolean')
        records.append(TrialRecord(state, weight, matches, exceeds))
    return TrialSet(references, tuple(records))
