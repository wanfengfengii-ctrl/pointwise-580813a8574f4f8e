import hashlib
import json

from batch.references import require_id
from .evidence import summarize_evidence
from .issue_store import FrozenIssue, IssueStore
from .revision_store import RevisionStore
from .revisions import StationRevision, load_revision


def _encode(revision: StationRevision, issue_id: int) -> bytes:
    identity = {
        'batch_id': revision.batch_id,
        'station': revision.station,
        'revision_id': revision.revision_id,
        'issue_id': issue_id,
    }
    rows = [
        {'state': row.state, 'likelihood': str(row.likelihood), 'exceedance': str(row.exceedance)}
        for row in summarize_evidence(revision.trials)
    ]
    body = json.dumps({**identity, 'references': revision.trials.references.names, 'evidence': rows},
                      sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    outer = {**identity, 'version': 1, 'sha256': digest, 'body': body}
    return json.dumps(outer, sort_keys=True, separators=(',', ':')).encode('utf-8')


def issue(store: IssueStore, revision_id: int) -> FrozenIssue:
    require_id(revision_id, 'revision id')

    def encode(issue_id: int) -> bytes:
        revision = load_revision(RevisionStore(store.connection), revision_id)
        return _encode(revision, issue_id)

    return store.freeze_item(revision_id, encode)


def reissue(store: IssueStore, issue_id: int) -> FrozenIssue:
    frozen = store.load_issue(require_id(issue_id, 'issue id'))
    if frozen is None:
        raise KeyError(f'unknown issue {issue_id}')
    return frozen
