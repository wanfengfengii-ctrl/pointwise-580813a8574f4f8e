from dataclasses import dataclass
from fractions import Fraction

RationalInput = Fraction | int | str


def exact_fraction(value, field: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (Fraction, int, str)):
        raise ValueError(f'{field} must be an exact rational number')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f'{field} must be an exact rational number') from exc


@dataclass(frozen=True)
class IsolationLine:
    value: Fraction


def validate_isolation_line(value: RationalInput | IsolationLine) -> IsolationLine:
    if isinstance(value, IsolationLine):
        value = value.value
    line = exact_fraction(value, 'isolation line')
    if not 0 <= line <= 1:
        raise ValueError('isolation line must be in [0, 1]')
    return IsolationLine(line)
