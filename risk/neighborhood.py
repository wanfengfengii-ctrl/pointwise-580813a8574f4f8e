"""Exact sum-reading neighborhood limits for two independent station measures.

For a named joint state each station contributes a match measure and an
exceedance subset measure (the exceedance measure is dominated by the match
measure).  The two station readings are conditionally independent given the
state, so joint measures are convolutions.  For a target sum ``s`` and a
positive radius ``epsilon`` we need the mass landing in the closed interval
``[s - epsilon, s + epsilon]``.

Every component is either a point mass or a uniform measure on a closed
interval, so the convolution of two components is one of:

* atom + atom  -> an atom;
* atom + interval -> a uniform interval;
* interval + interval -> a trapezoidal (piecewise-linear) measure.

The neighborhood mass of each convolution is a polynomial in ``epsilon`` whose
orders are 0, 1 or 2.  We accumulate the exact coefficients of the matching
denominator D and the double-exceedance numerator N, order by order.  The first
nonzero denominator order is ``support_order`` and the limit of
N(epsilon)/D(epsilon) as epsilon -> 0+ is the ratio of the leading
coefficients.  Components may contribute more than one order (for example a
ramp/plateau kink carries both a linear and a quadratic term).
"""
from dataclasses import dataclass
from fractions import Fraction

from station.distribution import Atom, Interval, Measure


@dataclass(frozen=True)
class NeighborhoodResult:
    supported: bool
    support_order: int | None
    limit: Fraction | None


def _atom_atom(target: Fraction, left: Atom, right: Atom):
    if left.position + right.position == target:
        yield 0, left.mass * right.mass


def _atom_interval(target: Fraction, atom: Atom, interval: Interval):
    """Neighborhood polynomial of an atom plus a uniform interval.

    The sum is uniform on [a + lo, a + hi] with a density jump at both ends.
    An interior target captures 2 * density * epsilon; an endpoint captures
    density * epsilon.  Both are purely order one.
    """
    lo = atom.position + interval.lo
    hi = atom.position + interval.hi
    density = atom.mass * interval.mass / (interval.hi - interval.lo)
    if lo < target < hi:
        yield 1, 2 * density
    elif target == lo or target == hi:
        yield 1, density


def _interval_interval(target: Fraction, left: Interval, right: Interval):
    """Neighborhood polynomial of the convolution of two uniform intervals.

    For intervals of masses m1, m2 with half-widths u = (b - a) / 2 and
    v = (d - c) / 2, the joint density on the sum support [A, B] (where
    A = a + c and B = b + d) is a trapezoid:

    * a linear ramp rises from zero with slope m1 m2 / (4 u v);
    * a flat plateau of density m1 m2 / (2 max(u, v)) follows when u != v;
    * a linear ramp falls back to zero with the opposite slope.

    The neighborhood mass is therefore:

    * a purely quadratic term at the outer tips where the density is zero;
    * a linear term at every interior point (ramp, ramp/plateau kink or the
      flat plateau), where a small window captures 2 * local_density * eps;
    * an additional quadratic correction at a ramp/plateau kink.

    Only atom + atom convolutions produce an order-zero (epsilon-independent)
    mass; interval convolutions always vanish as the window shrinks.
    """
    a, b = left.lo, left.hi
    c, d = right.lo, right.hi
    support_lo, support_hi = a + c, b + d
    if not support_lo <= target <= support_hi:
        return
    u = (b - a) / 2
    v = (d - c) / 2
    half_min = min(u, v)
    weight = left.mass * right.mass
    ramp_slope = weight / (4 * u * v)
    plateau_density = weight / (2 * max(u, v))
    up_kink = support_lo + 2 * half_min
    down_kink = support_hi - 2 * half_min

    if target == support_lo or target == support_hi:
        # Zero density at an outer tip: the adjacent ramp gives slope/2 * eps^2.
        # Checked first because a tip can coincide with a kink position.
        yield 2, ramp_slope / 2
        return
    if u != v and (target == up_kink or target == down_kink):
        # One window side is the plateau (density * epsilon); the other is the
        # ramp ending at the kink (density * epsilon - slope/2 * epsilon^2).
        yield 1, 2 * plateau_density
        yield 2, -ramp_slope / 2
        return
    if u == v and target == up_kink:
        # The single peak where the two ramps of an equal-width triangle meet:
        # both window sides are ramps, giving 2 * density * eps - slope * eps^2.
        peak_density = ramp_slope * (target - support_lo)
        yield 1, 2 * peak_density
        yield 2, -ramp_slope
        return
    # Any other interior point: a strictly interior ramp or flat plateau.  The
    # local density is positive and the neighborhood mass is exactly
    # 2 * local_density * epsilon for sufficiently small epsilon.
    if target < up_kink:
        local_density = ramp_slope * (target - support_lo)
    elif target > down_kink:
        local_density = ramp_slope * (support_hi - target)
    else:
        local_density = plateau_density
    yield 1, 2 * local_density


def _convolution_terms(target: Fraction, left: Measure, right: Measure):
    for left_atom in left.atoms:
        for right_atom in right.atoms:
            yield from _atom_atom(target, left_atom, right_atom)
    for atom in left.atoms:
        for interval in right.intervals:
            yield from _atom_interval(target, atom, interval)
    for interval in left.intervals:
        for atom in right.atoms:
            yield from _atom_interval(target, atom, interval)
    for left_interval in left.intervals:
        for right_interval in right.intervals:
            yield from _interval_interval(target, left_interval, right_interval)


def convolution_coefficients(target: Fraction, left: Measure,
                             right: Measure) -> dict[int, Fraction]:
    """Exact epsilon-polynomial coefficients (order -> coefficient) of the
    neighborhood mass of the convolution of two measures around target."""
    coefficients: dict[int, Fraction] = {}
    for order, coefficient in _convolution_terms(target, left, right):
        coefficients[order] = coefficients.get(order, Fraction(0)) + coefficient
    return coefficients


def neighborhood_limit(target: Fraction, left_match: Measure, left_exceed: Measure,
                       right_match: Measure, right_exceed: Measure) -> NeighborhoodResult:
    denominator = convolution_coefficients(target, left_match, right_match)
    numerator = convolution_coefficients(target, left_exceed, right_exceed)
    if not denominator or all(value == 0 for value in denominator.values()):
        return NeighborhoodResult(False, None, None)
    support_order = min(order for order, value in denominator.items() if value > 0)
    leading_denominator = denominator[support_order]
    leading_numerator = numerator.get(support_order, Fraction(0))
    # Lower-order numerator terms cannot exist without a matching denominator term
    # because the exceedance measures are dominated by the match measures.
    limit = leading_numerator / leading_denominator
    return NeighborhoodResult(True, support_order, limit)
