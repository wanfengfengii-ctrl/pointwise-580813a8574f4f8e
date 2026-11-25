"""Binding of two V2 sum items into a per-state aligned assessment context."""
from dataclasses import dataclass
from fractions import Fraction

from batch.policy import IsolationLine, RationalInput, validate_isolation_line
from batch.priors import JointPrior, validate_prior
from batch.references import ReferencePair, make_reference_pair
from intake.archive import IntakeArchive
from intake.envelope import load_object
from intake.receipt import get_received
from intake.sum_validate import StateMeasure, parse_sum_body


@dataclass(frozen=True)
class SumAssessmentContext:
    batch_id: str
    references: ReferencePair
    items: tuple
    prior: JointPrior
    isolation_line: IsolationLine
    sum_reading: Fraction
    left: tuple[StateMeasure, ...]
    right: tuple[StateMeasure, ...]


def bind_sum_context(archive: IntakeArchive, receipt_ids, prior: JointPrior,
                     isolation_line: RationalInput | IsolationLine,
                     sum_reading: Fraction) -> SumAssessmentContext:
    if not isinstance(receipt_ids, (tuple, list)) or len(receipt_ids) != 2:
        raise ValueError('two ordered receipt ids are required')
    left_item, right_item = (get_received(archive, receipt_id) for receipt_id in receipt_ids)
    left, right = left_item.envelope, right_item.envelope
    if left.version != 2 or right.version != 2:
        raise ValueError('assess_sum requires two V2 sum-reading items')
    if left.batch_id != right.batch_id:
        raise ValueError('items belong to different batches')
    if left.station == right.station:
        raise ValueError('items must come from different stations')
    left_body = load_object(left.body, 'left sum body')
    right_body = load_object(right.body, 'right sum body')
    left_refs = make_reference_pair(left_body.get('references'))
    right_refs = make_reference_pair(right_body.get('references'))
    references = left_refs.canonical()
    right_refs.permutation_to(references)
    left_states = parse_sum_body(left.body, left_refs, references)
    right_states = parse_sum_body(right.body, right_refs, references)
    bound_prior = validate_prior(prior, left.batch_id, references)
    line = validate_isolation_line(isolation_line)
    return SumAssessmentContext(
        left.batch_id, references, (left_item, right_item), bound_prior, line,
        sum_reading, left_states, right_states,
    )
