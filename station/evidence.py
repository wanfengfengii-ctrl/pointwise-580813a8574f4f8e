from dataclasses import dataclass
from fractions import Fraction

from batch.references import JointState, joint_states
from .trials import TrialSet


@dataclass(frozen=True)
class StateEvidence:
    state: JointState
    likelihood: Fraction
    exceedance: Fraction


def summarize_evidence(trials: TrialSet) -> tuple[StateEvidence, ...]:
    states = joint_states()
    observed = dict.fromkeys(states, Fraction(0))
    exceeded = dict.fromkeys(states, Fraction(0))
    for row in trials.rows:
        if row.matches:
            observed[row.state] += row.weight
            if row.exceeds:
                exceeded[row.state] += row.weight
    return tuple(StateEvidence(state, observed[state], exceeded[state]) for state in states)
