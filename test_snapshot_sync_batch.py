import unittest

from snapshot_sync import _insert_rows


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))


class BatchInsertTests(unittest.TestCase):
    def test_batches_rows_into_multi_row_statements(self):
        conn = FakeConn()
        rows = [{"symbol": f"{i:04d}.TW", "close": float(i)} for i in range(1201)]
        count = _insert_rows(conn, "stock_prices", ["symbol", "close"], rows, batch_size=500)
        self.assertEqual(count, 1201)
        self.assertEqual(len(conn.calls), 3)
        sql, params = conn.calls[0]
        self.assertEqual(sql.count("("), 501)
        self.assertEqual(len(params), 1000)
        self.assertEqual(conn.calls[2][1]["p0_0"], "1000.TW")
        self.assertEqual(conn.calls[2][1]["p200_0"], "1200.TW")

    def test_empty_rows_do_nothing(self):
        conn = FakeConn()
        self.assertEqual(_insert_rows(conn, "t", ["a"], []), 0)
        self.assertEqual(conn.calls, [])


if __name__ == "__main__":
    unittest.main()
