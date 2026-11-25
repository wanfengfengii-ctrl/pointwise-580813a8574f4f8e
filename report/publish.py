from .records import ReportDraft
from .retrieve import ReportBundle
from .store import ReportStore


def publish(store: ReportStore, draft: ReportDraft) -> ReportBundle:
    report, receipt = store.commit(draft)
    return ReportBundle(report, receipt)
