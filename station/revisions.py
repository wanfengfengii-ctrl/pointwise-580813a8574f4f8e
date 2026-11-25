from dataclasses import dataclass
from typing import Iterable

from batch.catalog import get_batch
from batch.references import make_reference_pair, require_id, require_name
from batch.store import BatchStore
from .revision_store import RevisionStore, StoredRevision
from .trials import TrialSet, validate_trials


@dataclass(frozen=True)
class StationRevision:
    revision_id: int
    batch_id: str
    station: str
    parent_id: int | None
    trials: TrialSet


def _snapshot(record: StoredRevision) -> StationRevision:
    return StationRevision(record.revision_id, record.batch_id, record.station,
                           record.parent_id, record.trials)


def revise(catalog: BatchStore, store: RevisionStore, batch_id: str, station: str,
           rows: Iterable, *, parent_id: int | None = None,
           reference_names=None) -> StationRevision:
    batch = get_batch(catalog, batch_id)
    require_name(station, 'station')
    if parent_id is not None:
        require_id(parent_id, 'parent revision')
    references = batch.references
    if reference_names is not None:
        references = make_reference_pair(reference_names)
        references.permutation_to(batch.references)
    trials = validate_trials(references, rows)
    return _snapshot(store.commit_revision(batch.batch_id, station, parent_id, trials))


def load_revision(store: RevisionStore, revision_id: int) -> StationRevision:
    stored = store.load_revision(require_id(revision_id, 'revision id'))
    if stored is None:
        raise KeyError(f'unknown revision {revision_id}')
    return _snapshot(stored)
