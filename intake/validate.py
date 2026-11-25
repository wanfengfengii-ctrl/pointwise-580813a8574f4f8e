from dataclasses import dataclass
import hashlib

from batch.references import ReferencePair, make_reference_pair
from .envelope import Envelope, load_object, read_identity


@dataclass(frozen=True)
class VerifiedItem:
    envelope: Envelope
    references: ReferencePair


def validate_envelope(envelope: Envelope) -> VerifiedItem:
    if hashlib.sha256(envelope.body).hexdigest() != envelope.digest:
        raise ValueError('body digest does not match envelope')
    body = load_object(envelope.body, 'body')
    if read_identity(body) != envelope.identity:
        raise ValueError('body provenance does not match envelope')
    references = make_reference_pair(body.get('references'))
    if envelope.version == 2:
        # Full structural and domination validation of the four-state measures.
        from .sum_validate import parse_sum_body
        parse_sum_body(envelope.body, references, references.canonical())
    return VerifiedItem(envelope, references)
