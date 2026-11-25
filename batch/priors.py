from dataclasses import dataclass
from fractions import Fraction

from .policy import RationalInput, exact_fraction
from .references import ReferencePair, align_state, joint_states, require_name


@dataclass(frozen=True)
class JointPrior:
    batch_id: str
    references: ReferencePair
    masses: tuple[RationalInput, ...]


def validate_prior(prior: JointPrior, batch_id: str, references: ReferencePair) -> JointPrior:
    if not isinstance(prior, JointPrior):
        raise ValueError('a joint prior is required')
    if require_name(prior.batch_id, 'prior batch') != batch_id:
        raise ValueError('prior belongs to another batch')
    if not isinstance(prior.references, ReferencePair):
        raise ValueError('prior must declare two named references')
    prior.references.permutation_to(references)
    states = joint_states()
    if not isinstance(prior.masses, (list, tuple)) or len(prior.masses) != len(states):
        raise ValueError('prior must supply all four masses')
    masses = tuple(exact_fraction(value, 'prior mass') for value in prior.masses)
    if any(mass < 0 for mass in masses) or sum(masses, Fraction(0)) != 1:
        raise ValueError('prior masses must be nonnegative and sum to one')
    aligned = {
        align_state(state, prior.references, references): mass
        for state, mass in zip(states, masses, strict=True)
    }
    return JointPrior(batch_id, references, tuple(aligned[state] for state in states))
