from dataclasses import dataclass
from fractions import Fraction

from batch.policy import IsolationLine, RationalInput, exact_fraction, validate_isolation_line
from batch.priors import JointPrior, validate_prior
from batch.references import JointState, ReferencePair, align_state, joint_states, make_reference_pair
from intake.archive import IntakeArchive
from intake.envelope import load_object
from intake.receipt import ReceivedItem, get_received


@dataclass(frozen=True)
class EvidencePair:
    likelihood: Fraction
    exceedance: Fraction


@dataclass(frozen=True)
class AssessmentContext:
    batch_id: str
    references: ReferencePair
    items: tuple[ReceivedItem, ReceivedItem]
    prior: JointPrior
    isolation_line: IsolationLine
    left: tuple[EvidencePair, ...]
    right: tuple[EvidencePair, ...]


def _decode_evidence(body: dict, source: ReferencePair,
                     target: ReferencePair) -> tuple[EvidencePair, ...]:
    entries = body.get('evidence')
    states = joint_states()
    if not isinstance(entries, list) or len(entries) != len(states):
        raise ValueError('item needs evidence for all four joint states')
    aligned: dict[JointState, EvidencePair] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not {'state', 'likelihood', 'exceedance'} <= entry.keys():
            raise ValueError('incomplete state evidence')
        state = align_state(entry['state'], source, target)
        if state in aligned:
            raise ValueError('duplicate evidence state')
        likelihood = exact_fraction(entry['likelihood'], 'likelihood')
        exceedance = exact_fraction(entry['exceedance'], 'exceedance')
        if not 0 <= exceedance <= likelihood:
            raise ValueError('state evidence must satisfy 0 <= exceedance <= likelihood')
        aligned[state] = EvidencePair(likelihood, exceedance)
    return tuple(aligned[state] for state in states)


def bind_context(archive: IntakeArchive, receipt_ids, prior: JointPrior,
                 isolation_line: RationalInput | IsolationLine) -> AssessmentContext:
    if not isinstance(receipt_ids, (tuple, list)) or len(receipt_ids) != 2:
        raise ValueError('two ordered receipt ids are required')
    left_item, right_item = (get_received(archive, receipt_id) for receipt_id in receipt_ids)
    left, right = left_item.envelope, right_item.envelope
    if left.batch_id != right.batch_id:
        raise ValueError('items belong to different batches')
    if left.station == right.station:
        raise ValueError('items must come from different stations')
    left_body = load_object(left.body, 'left body')
    right_body = load_object(right.body, 'right body')
    left_refs = make_reference_pair(left_body.get('references'))
    right_refs = make_reference_pair(right_body.get('references'))
    references = left_refs.canonical()
    right_refs.permutation_to(references)
    bound_prior = validate_prior(prior, left.batch_id, references)
    line = validate_isolation_line(isolation_line)
    return AssessmentContext(
        left.batch_id, references, (left_item, right_item), bound_prior, line,
        _decode_evidence(left_body, left_refs, references),
        _decode_evidence(right_body, right_refs, references),
    )
