import json
import sqlite3
import unittest

from intake import IntakeArchive, get_received, receive
from tests.test_risk import pack_complete


class ReceiveTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.archive = IntakeArchive(self.db)
        self.archive.initialize()
        self.raw = pack_complete('甲', [(1, 0), (0, 0), (0, 0), (1, 1)])

    def count(self):
        return self.db.execute('SELECT count(*) FROM received_items').fetchone()[0]

    def test_bad_digest(self):
        changed = json.loads(self.raw)
        body = json.loads(changed['body'])
        body['evidence'][0]['likelihood'] = '2'
        changed['body'] = json.dumps(body)
        with self.assertRaisesRegex(ValueError, 'digest'):
            receive(self.archive, json.dumps(changed).encode('utf-8'))
        self.assertEqual(self.count(), 0)
        self.assertEqual(receive(self.archive, self.raw).envelope.raw, self.raw)

    def test_duplicate_delivery(self):
        first = receive(self.archive, self.raw)
        second = receive(self.archive, self.raw)
        self.assertEqual(first, second)
        self.assertEqual(first, get_received(self.archive, first.receipt_id))
        self.assertEqual(self.count(), 1)

    def test_identity_conflict(self):
        original = receive(self.archive, self.raw)
        changed = pack_complete('甲', [(2, 0), (0, 0), (0, 0), (1, 1)])
        with self.assertRaisesRegex(ValueError, 'identity'):
            receive(self.archive, changed)
        self.assertEqual(get_received(self.archive, original.receipt_id), original)
        self.assertEqual(original.envelope.raw, self.raw)
        self.assertEqual(self.count(), 1)

    def test_invalid_envelope(self):
        changed = json.loads(self.raw)
        changed['revision_id'] = 99
        with self.assertRaisesRegex(ValueError, 'provenance'):
            receive(self.archive, json.dumps(changed).encode('utf-8'))
        for raw in (b'{}', b'\xff', b'{"version":1,"version":1}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                receive(self.archive, raw)
        self.assertEqual(self.count(), 0)
