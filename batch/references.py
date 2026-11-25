from dataclasses import dataclass
from itertools import product

JointState = tuple[int, int]
_STATES: tuple[JointState, ...] = tuple(product((0, 1), repeat=2))


def require_name(value, field: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or not value.isprintable()):
        raise ValueError(f'{field} must be a nonempty printable name')
    return value


def require_id(value, field: str) -> int:
    if type(value) is not int or not 0 < value <= (1 << 63) - 1:
        raise ValueError(f'{field} must be a positive SQLite integer')
    return value


@dataclass(frozen=True)
class ReferencePair:
    names: tuple[str, str]

    def __post_init__(self):
        if not isinstance(self.names, tuple) or len(self.names) != 2:
            raise ValueError('exactly two reference names are required')
        first, second = (require_name(name, 'reference') for name in self.names)
        if first == second:
            raise ValueError('reference names must differ')

    def canonical(self) -> 'ReferencePair':
        return ReferencePair(tuple(sorted(self.names)))

    def permutation_to(self, target: 'ReferencePair') -> tuple[int, int]:
        if self.names == target.names:
            return (0, 1)
        if self.names[::-1] == target.names:
            return (1, 0)
        raise ValueError('reference names do not match')


def make_reference_pair(names) -> ReferencePair:
    if not isinstance(names, (list, tuple)):
        raise ValueError('reference names must be an ordered pair')
    return ReferencePair(tuple(names))


def joint_states() -> tuple[JointState, ...]:
    return _STATES


def validate_state(state) -> JointState:
    if not isinstance(state, (list, tuple)) or len(state) != 2:
        raise ValueError('a joint state needs two reference bits')
    if any(type(bit) is not int or bit not in (0, 1) for bit in state):
        raise ValueError('reference bits must be integers 0 or 1')
    return (state[0], state[1])


def align_state(state, source: ReferencePair, target: ReferencePair) -> JointState:
    first, second = source.permutation_to(target)
    bits = validate_state(state)
    return (bits[first], bits[second])
