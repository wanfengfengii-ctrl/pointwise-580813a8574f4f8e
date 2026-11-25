from batch.references import require_id
from .archive import ArchiveEntry, IntakeArchive
from .envelope import parse_envelope
from .validate import validate_envelope

ReceivedItem = ArchiveEntry


def receive(archive: IntakeArchive, raw: bytes) -> ReceivedItem:
    return archive.record(validate_envelope(parse_envelope(raw)))


def get_received(archive: IntakeArchive, receipt_id: int) -> ReceivedItem:
    entry = archive.get(require_id(receipt_id, 'receipt id'))
    if entry is None:
        raise KeyError(f'unknown receipt {receipt_id}')
    return entry
