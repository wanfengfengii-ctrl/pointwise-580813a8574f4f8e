from dataclasses import dataclass


@dataclass(frozen=True)
class SignReceipt:
    report_id: int
    receipt_number: str


def make_sign_receipt(report_id: int) -> SignReceipt:
    return SignReceipt(report_id, f'S-{report_id}')


def restore_sign_receipt(report_id: int, receipt_number: str) -> SignReceipt:
    return SignReceipt(report_id, receipt_number)
