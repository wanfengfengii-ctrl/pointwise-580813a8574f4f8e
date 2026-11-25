from dataclasses import dataclass

from .policy import IsolationLine, RationalInput, validate_isolation_line
from .references import ReferencePair, make_reference_pair, require_name
from .store import BatchStore, StoredBatch


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    references: ReferencePair
    isolation_line: IsolationLine


def _restore(stored: StoredBatch) -> BatchRecord:
    return BatchRecord(
        stored.batch_id,
        make_reference_pair((stored.reference_a, stored.reference_b)),
        validate_isolation_line(stored.isolation_line),
    )


def register(store: BatchStore, batch_id: str, reference_names,
             isolation_line: RationalInput | IsolationLine) -> BatchRecord:
    require_name(batch_id, 'batch id')
    references = make_reference_pair(reference_names).canonical()
    line = validate_isolation_line(isolation_line)
    candidate = StoredBatch(batch_id, *references.names, str(line.value))
    stored = store.register_if_absent(candidate)
    if candidate != stored:
        raise ValueError('batch already registered with different references or line')
    return _restore(stored)


def get_batch(store: BatchStore, batch_id: str) -> BatchRecord:
    stored = store.load(require_name(batch_id, 'batch id'))
    if stored is None:
        raise KeyError(f'unknown batch {batch_id}')
    return _restore(stored)
