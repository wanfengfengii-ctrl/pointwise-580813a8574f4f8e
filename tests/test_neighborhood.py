import unittest
from fractions import Fraction as F

from station.distribution import Atom, Interval, Measure
from risk.neighborhood import convolution_coefficients, neighborhood_limit


def interval(lo, hi, mass):
    return Interval(F(lo), F(hi), F(mass))


def atom(position, mass):
    return Atom(F(position), F(mass))


class ConvolutionGeometryTests(unittest.TestCase):
    def test_atom_atom_is_order_zero(self):
        left = Measure((atom(1, 2),), ())
        right = Measure((atom(3, 5),), ())
        self.assertEqual(convolution_coefficients(F(4), left, right), {0: F(10)})
        self.assertEqual(convolution_coefficients(F(0), left, right), {})

    def test_atom_interval_endpoint_and_interior(self):
        left = Measure((atom(0, 1),), ())
        right = Measure((), (interval(0, 2, 4),))  # density 2
        # Interior target 1: 2 * density * eps = 4 eps.
        self.assertEqual(convolution_coefficients(F(1), left, right), {1: F(4)})
        # Endpoint target 0: density * eps = 2 eps.
        self.assertEqual(convolution_coefficients(F(0), left, right), {1: F(2)})

    def test_interval_tip_is_quadratic(self):
        left = Measure((), (interval(0, 2, 1),))
        right = Measure((), (interval(0, 2, 1),))
        # Equal-width triangle, tip at 0: slope 1/4, coefficient slope/2 = 1/8.
        self.assertEqual(convolution_coefficients(F(0), left, right), {2: F(1, 8)})

    def test_equal_width_triangle_center(self):
        left = Measure((), (interval(0, 2, 1),))
        right = Measure((), (interval(0, 2, 1),))
        # Center 2: order-one coefficient 2 * density (density 1/2) and an
        # order-two correction -slope (slope 1/4).
        self.assertEqual(convolution_coefficients(F(2), left, right),
                         {1: F(1), 2: F(-1, 4)})

    def test_unequal_width_plateau_is_order_one(self):
        # u = 1, v = 3/2; plateau density = weight / (2 max(u,v)) = 2/3.
        left = Measure((), (interval(0, 2, 1),))
        right = Measure((), (interval(1, 4, 2),))
        # A strictly interior plateau point (3.5): coefficient 2 * 2/3 = 4/3.
        coeffs = convolution_coefficients(F(7, 2), left, right)
        self.assertEqual(coeffs, {1: F(4, 3)})

    def test_ramp_plateau_kink_has_quadratic_correction(self):
        left = Measure((), (interval(0, 2, 1),))
        right = Measure((), (interval(1, 4, 2),))
        # Up-kink at A + 2 min(u,v) = 1 + 2 = 3.
        coeffs = convolution_coefficients(F(3), left, right)
        self.assertEqual(coeffs, {1: F(4, 3), 2: F(-1, 6)})

    def test_polynomial_matches_direct_integration(self):
        """Reconstructed epsilon polynomial equals an independent exact integral
        for every atom/atom and atom/interval component in the measure."""
        left = Measure((atom(0, 1), atom(2, 3)),
                       (interval(0, 4, 2), interval(1, 3, 5)))
        right = Measure((atom(-1, 2), atom(3, 1)), ())

        def direct(target, eps):
            lo, hi = target - eps, target + eps
            total = F(0)

            def overlap(a, b):
                return max(F(0), min(b, hi) - max(a, lo))

            for a in left.atoms:
                for b in right.atoms:
                    if lo <= a.position + b.position <= hi:
                        total += a.mass * b.mass
            for iv in left.intervals:
                for a in right.atoms:
                    total += a.mass * iv.mass / (iv.hi - iv.lo) * overlap(
                        iv.lo + a.position, iv.hi + a.position)
            return total

        for target in (F(0), F(1), F(2), F(-1), F(3)):
            coeffs = convolution_coefficients(target, left, right)
            if not coeffs:
                self.assertEqual(direct(target, F(1, 1000)), 0)
                continue
            for eps in (F(1, 1000), F(3, 1000)):
                expected = sum(c * eps ** k for k, c in coeffs.items())
                self.assertEqual(expected, direct(target, eps))

    def test_limit_uses_leading_order_with_dominated_exceedance(self):
        match_left = Measure((atom(0, 1),), (interval(0, 2, 1),))
        match_right = Measure((atom(0, 1),), (interval(0, 2, 1),))
        # Exceedance keeps only the point masses, so only the atom-atom term
        # contributes to N while D also includes interval terms.
        exceed_left = Measure((atom(0, 1),), ())
        exceed_right = Measure((atom(0, 1),), ())
        result = neighborhood_limit(F(0), match_left, exceed_left,
                                    match_right, exceed_right)
        self.assertTrue(result.supported)
        # D at target 0: atom-atom order 0 = 1 dominates; N order 0 = 1.
        self.assertEqual(result.support_order, 0)
        self.assertEqual(result.limit, F(1))


if __name__ == '__main__':
    unittest.main()
