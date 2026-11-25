from dataclasses import dataclass

from batch.references import require_id
from .receipts import SignReceipt
from .records import SignedReport
from .store import ReportStore


@dataclass(frozen=True)
class ReportBundle:
    report: SignedReport
    receipt: SignReceipt


def read(store: ReportStore, report_id: int) -> ReportBundle | None:
    stored = store.load_bundle(require_id(report_id, 'report id'))
    return None if stored is None else ReportBundle(*stored)
