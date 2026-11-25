"""Parsing and validation of V2 sum-reading distribution bodies."""
from dataclasses import dataclass
from fractions import Fraction

from batch.policy import exact_fraction
from batch.references import JointState, ReferencePair, align_state, joint_states
from station.distribution import Atom, Interval, Measure
from .envelope import load_object


@dataclass(frozen=True)
class StateMeasure:
    state: JointState
    match: Measure
    exceed: Measure


@dataclass(frozen=True)
class SumBody:
    references: ReferencePair
    states: tuple[StateMeasure, ...]


def _parse_measure(value, label: str) -> Measure:
    if not isinstance(value, dict) or set(value.keys()) != {'components'}:
        raise ValueError(f'{label} must be a measure with a components list')
    components = value['components']
    if not isinstance(components, list):
        raise ValueError(f'{label} components must be a list')
    atoms: list[Atom] = []
    intervals: list[Interval] = []
    for index, component in enumerate(components, start=1):
        if not isinstance(component, list) or len(component) not in (2, 3):
            raise ValueError(f'{label} component {index} must be a point or interval encoding')
        if len(component) == 2:
            position = exact_fraction(component[0], f'{label} component {index} position')
            mass = exact_fraction(component[1], f'{label} component {index} mass')
            if mass < 0:
                raise ValueError(f'{label} component {index} mass must be nonnegative')
            atoms.append(Atom(position, mass))
        else:
            lo = exact_fraction(component[0], f'{label} component {index} lo')
            hi = exact_fraction(component[1], f'{label} component {index} hi')
            mass = exact_fraction(component[2], f'{label} component {index} mass')
            if lo >= hi:
                raise ValueError(f'{label} interval {index} must have positive width')
            if mass < 0:
                raise ValueError(f'{label} interval {index} mass must be nonnegative')
            intervals.append(Interval(lo, hi, mass))
    return Measure(tuple(atoms), tuple(intervals))


def _dominates(match: Measure, exceed: Measure, label: str) -> None:
    """Require the exceedance measure to be dominated by the match measure.

    Point masses are compared directly at shared positions.  For the uniform
    pieces, the rational line is split at every interval endpoint and the
    exceedance density must never exceed the match density on a segment.
    """
    match_atoms = {atom.position: atom.mass for atom in match.atoms}
    exceed_atoms = {atom.position: atom.mass for atom in exceed.atoms}
    for position, mass in exceed_atoms.items():
        if mass > match_atoms.get(position, Fraction(0)):
            raise ValueError(f'{label} exceedance point mass exceeds the match mass')
    endpoints = sorted({
        point
        for measure in (match, exceed)
        for interval in measure.intervals
        for point in (interval.lo, interval.hi)
    })
    for lo, hi in zip(endpoints, endpoints[1:]):
        if lo >= hi:
            continue
        midpoint = (lo + hi) / 2

        def density(measure: Measure) -> Fraction:
            total = Fraction(0)
            for interval in measure.intervals:
                if interval.lo <= midpoint <= interval.hi:
                    total += interval.mass / (interval.hi - interval.lo)
            return total

        if density(exceed) > density(match):
            raise ValueError(f'{label} exceedance density exceeds the match density on [{lo}, {hi}]')


def parse_sum_body(body: bytes, source: ReferencePair, target: ReferencePair) -> tuple[StateMeasure, ...]:
    fields = load_object(body, 'sum body')
    entries = fields.get('distributions')
    states = joint_states()
    if not isinstance(entries, list) or len(entries) != len(states):
        raise ValueError('sum item needs distributions for all four joint states')
    aligned: dict[JointState, StateMeasure] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or not {'state', 'match', 'exceed'} <= entry.keys():
            raise ValueError(f'distribution {index} is incomplete')
        state = align_state(entry['state'], source, target)
        if state in aligned:
            raise ValueError('duplicate distribution state')
        match = _parse_measure(entry['match'], f'state {state} match')
        exceed = _parse_measure(entry['exceed'], f'state {state} exceed')
        _dominates(match, exceed, f'state {state}')
        aligned[state] = StateMeasure(state, match, exceed)
    return tuple(aligned[state] for state in states)
