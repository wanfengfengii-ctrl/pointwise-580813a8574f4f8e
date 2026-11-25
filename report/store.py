import sqlite3

from .receipts import SignReceipt, make_sign_receipt, restore_sign_receipt
from .records import ReportDraft, SignedReport, encode_report, restore_report


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS signed_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sign_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES signed_reports(report_id),
                receipt_number TEXT NOT NULL UNIQUE
            );
        ''')

    def commit(self, draft: ReportDraft) -> tuple[SignedReport, SignReceipt]:
        encoded = encode_report(draft)
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            cursor = db.execute('INSERT INTO signed_reports (snapshot) VALUES (?)', (encoded,))
            report_id = cursor.lastrowid
            receipt = make_sign_receipt(report_id)
            db.execute('''
                INSERT INTO sign_receipts (report_id, receipt_number) VALUES (?, ?)
            ''', (receipt.report_id, receipt.receipt_number))
        return SignedReport(report_id, draft), receipt

    def load_bundle(self, report_id: int) -> tuple[SignedReport, SignReceipt] | None:
        row = self.connection.execute('''
            SELECT report.snapshot, receipt.receipt_number
            FROM signed_reports AS report
            JOIN sign_receipts AS receipt USING (report_id)
            WHERE report.report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        encoded, receipt_number = row
        return restore_report(report_id, encoded), restore_sign_receipt(report_id, receipt_number)
