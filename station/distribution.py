"""V2 sum-reading distributions built from station trial rows and per-row supports.

Each trial row carries a joint state, a weight, a match flag and an exceedance flag.
A support is the closed rational interval ``[lo, hi]`` from which that row's reading
is drawn.  A row's weight is spread uniformly over a positive-width interval and
placed as a point mass when the two endpoints coincide (a zero-width interval).
Only the aggregated per-state measures leave the station; the original rows and
the per-row support table stay behind.
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from batch.policy import exact_fraction
from batch.references import JointState, joint_states
from .revisions import StationRevision
from .trials import TrialSet


@dataclass(frozen=True)
class Atom:
    """A point mass at ``position``."""

    position: Fraction
    mass: Fraction


@dataclass(frozen=True)
class Interval:
    """A uniform density ``mass / (hi - lo)`` over the closed interval ``[lo, hi]``."""

    lo: Fraction
    hi: Fraction
    mass: Fraction


@dataclass(frozen=True)
class Measure:
    atoms: tuple[Atom, ...] = ()
    intervals: tuple[Interval, ...] = ()

    def total(self) -> Fraction:
        mass = sum((atom.mass for atom in self.atoms), Fraction(0))
        return mass + sum((interval.mass for interval in self.intervals), Fraction(0))


@dataclass(frozen=True)
class StateDistribution:
    state: JointState
    match: Measure
    exceed: Measure


@dataclass(frozen=True)
class RevisionDistribution:
    references: tuple[str, ...]
    states: tuple[StateDistribution, ...]


def validate_supports(trials: TrialSet, supports: Iterable) -> tuple[tuple[Fraction, Fraction], ...]:
    try:
        ordered = tuple(supports)
    except TypeError as exc:
        raise ValueError('supports must be an ordered sequence of (lo, hi) pairs') from exc
    if len(ordered) != len(trials.rows):
        raise ValueError('supports must cover every trial row in revision order')
    normalized = []
    for index, support in enumerate(ordered, start=1):
        if not isinstance(support, (tuple, list)) or len(support) != 2:
            raise ValueError(f'support {index} must be a (lo, hi) pair')
        lo = exact_fraction(support[0], f'support {index} lo')
        hi = exact_fraction(support[1], f'support {index} hi')
        if lo > hi:
            raise ValueError(f'support {index} must satisfy lo <= hi')
        normalized.append((lo, hi))
    return tuple(normalized)


def _add(buckets: dict, key, mass: Fraction) -> None:
    if mass == 0:
        return
    buckets[key] = buckets.get(key, Fraction(0)) + mass


def _measure(records, supports) -> Measure:
    atoms: dict[Fraction, Fraction] = {}
    intervals: dict[tuple[Fraction, Fraction], Fraction] = {}
    for row, (lo, hi) in zip(records, supports, strict=True):
        if row.weight == 0:
            continue
        if lo == hi:
            _add(atoms, lo, row.weight)
        else:
            _add(intervals, (lo, hi), row.weight)
    return Measure(
        tuple(Atom(position, mass) for position, mass in sorted(atoms.items())),
        tuple(Interval(lo, hi, mass) for (lo, hi), mass in sorted(intervals.items())),
    )


def build_distribution(revision: StationRevision, supports: Iterable) -> RevisionDistribution:
    ordered = validate_supports(revision.trials, supports)
    paired = list(zip(revision.trials.rows, ordered, strict=True))
    distributions = []
    for state in joint_states():
        matched = [(row, support) for row, support in paired
                   if row.matches and row.state == state]
        exceed = [(row, support) for row, support in matched if row.exceeds]
        distributions.append(StateDistribution(
            state,
            _measure([row for row, _ in matched], [support for _, support in matched]),
            _measure([row for row, _ in exceed], [support for _, support in exceed]),
        ))
    return RevisionDistribution(revision.trials.references.names, tuple(distributions))
