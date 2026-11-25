"""V2 fixed-issue encoding for sum-reading reviews.

The V2 envelope reuses the V1 outer fields and body digest convention but sets
``version`` to 2.  The body keeps the four provenance fields and the two
reference names and adds a ``distributions`` array with one entry per named
joint state.  Each state carries two measures, ``match`` and ``exceed``:

* a point mass at reading ``r`` of mass ``m`` is encoded ``[r, m]``;
* a uniform measure on the positive-width closed interval ``[lo, hi]`` with
  total mass ``m`` is encoded ``[lo, hi, m]``.

All rational numbers are emitted as exact strings.  An empty measure is an
empty component list.
"""
import hashlib
import json

from batch.references import require_id
from .distribution import Measure, RevisionDistribution, StateDistribution, build_distribution
from .issue_store import FrozenIssue, IssueStore
from .revision_store import RevisionStore
from .revisions import StationRevision, load_revision


def supports_key(supports) -> str:
    """Canonical key so exactly equivalent endpoints (e.g. 0 and 0/2) collide."""
    return json.dumps([[str(lo), str(hi)] for lo, hi in supports],
                      sort_keys=True, separators=(',', ':'))


def _encode_measure(measure: Measure) -> dict:
    components = []
    for atom in measure.atoms:
        components.append([str(atom.position), str(atom.mass)])
    for interval in measure.intervals:
        components.append([str(interval.lo), str(interval.hi), str(interval.mass)])
    return {'components': components}


def _encode_state(state: StateDistribution) -> dict:
    return {
        'state': list(state.state),
        'match': _encode_measure(state.match),
        'exceed': _encode_measure(state.exceed),
    }


def _encode(revision: StationRevision, distribution: RevisionDistribution,
            issue_id: int) -> bytes:
    identity = {
        'batch_id': revision.batch_id,
        'station': revision.station,
        'revision_id': revision.revision_id,
        'issue_id': issue_id,
    }
    body = json.dumps({
        **identity,
        'references': list(revision.trials.references.names),
        'distributions': [_encode_state(state) for state in distribution.states],
    }, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    outer = {**identity, 'version': 2, 'sha256': digest, 'body': body}
    return json.dumps(outer, sort_keys=True, separators=(',', ':')).encode('utf-8')


def issue_sum(store: IssueStore, revision_id: int, supports) -> FrozenIssue:
    require_id(revision_id, 'revision id')
    revision = load_revision(RevisionStore(store.connection), revision_id)
    distribution = build_distribution(revision, supports)
    # ``build_distribution`` validated and normalized the endpoints; key on that
    # canonical form so 0 and 0/2 are recognized as the same support request.
    from .distribution import validate_supports
    ordered = validate_supports(revision.trials, supports)
    key = supports_key(ordered)

    def encode(issue_id: int) -> bytes:
        return _encode(revision, distribution, issue_id)

    return store.freeze_sum_item(revision_id, key, encode)
