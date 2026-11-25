from dataclasses import dataclass
import json
import re

from batch.references import require_id, require_name

_IDENTITY_KEYS = frozenset(('batch_id', 'station', 'revision_id', 'issue_id'))
_ENVELOPE_KEYS = _IDENTITY_KEYS | {'version', 'sha256', 'body'}


@dataclass(frozen=True)
class Envelope:
    batch_id: str
    station: str
    revision_id: int
    issue_id: int
    digest: str
    body: bytes
    raw: bytes

    @property
    def identity(self) -> tuple[str, str, int, int]:
        return self.batch_id, self.station, self.revision_id, self.issue_id


def _unique_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f'invalid JSON number {value}')


def load_object(raw: bytes, label: str) -> dict:
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f'{label} is not valid UTF-8 JSON: {exc}') from exc
    if not isinstance(result, dict):
        raise ValueError(f'{label} must be a JSON object')
    return result


def read_identity(fields: dict) -> tuple[str, str, int, int]:
    if not _IDENTITY_KEYS <= fields.keys():
        raise ValueError('incomplete issue identity')
    return (
        require_name(fields['batch_id'], 'batch id'),
        require_name(fields['station'], 'station'),
        require_id(fields['revision_id'], 'revision id'),
        require_id(fields['issue_id'], 'issue id'),
    )


def parse_envelope(raw: bytes) -> Envelope:
    if not isinstance(raw, bytes):
        raise ValueError('fixed item must be supplied as bytes')
    fields = load_object(raw, 'envelope')
    if fields.keys() != _ENVELOPE_KEYS:
        raise ValueError('incorrect envelope fields')
    version = fields['version']
    if type(version) is not int or version != 1:
        raise ValueError('unsupported envelope version')
    digest, body = fields['sha256'], fields['body']
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('invalid SHA-256 declaration')
    if not isinstance(body, str):
        raise ValueError('body must be JSON text')
    try:
        body_bytes = body.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('body must be valid UTF-8 text') from exc
    return Envelope(*read_identity(fields), digest, body_bytes, raw)
