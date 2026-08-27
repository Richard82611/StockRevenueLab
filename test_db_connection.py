import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import db_connection


class DatabaseConnectionTests(unittest.TestCase):
    def setUp(self):
        self.original_streamlit = db_connection.st

    def tearDown(self):
        db_connection.st = self.original_streamlit

    def set_secrets(self, secrets):
        db_connection.st = SimpleNamespace(secrets=secrets)

    def test_reads_nested_supabase_secrets(self):
        self.set_secrets(
            {
                "supabase": {
                    "SUPABASE_PROJECT_ID": "project123",
                    "SUPABASE_PASSWORD": "p@ss word",
                    "SUPABASE_POOLER_HOST": "pooler.example.com",
                }
            }
        )

        url, endpoint = db_connection._connection_url()

        self.assertEqual(
            url,
            "postgresql+psycopg2://postgres.project123:p%40ss%20word"
            "@pooler.example.com:5432/postgres?sslmode=require",
        )
        self.assertEqual(endpoint["host"], "pooler.example.com")

    def test_accepts_complete_database_url(self):
        self.set_secrets(
            {"DATABASE_URL": "postgres://dbuser:encoded%20password@db.example.com:5432/app"}
        )

        url, endpoint = db_connection._connection_url()

        self.assertEqual(
            url,
            "postgresql+psycopg2://dbuser:encoded%20password"
            "@db.example.com:5432/app?sslmode=require",
        )
        self.assertEqual(endpoint, {"mode": "DATABASE_URL"})

    def test_uses_project_pooler_default_when_host_is_missing(self):
        self.set_secrets(
            {
                "supabase": {
                    "SUPABASE_PROJECT_ID": "project123",
                    "SUPABASE_PASSWORD": "secret",
                }
            }
        )

        url, endpoint = db_connection._connection_url()

        self.assertIn("@aws-1-ap-southeast-1.pooler.supabase.com:5432/", url)
        self.assertEqual(endpoint["host"], "aws-1-ap-southeast-1.pooler.supabase.com")

    def test_reports_missing_password_without_values(self):
        self.set_secrets({"supabase": {"SUPABASE_PROJECT_ID": "project123"}})

        with self.assertRaisesRegex(ValueError, "DB_PASSWORD"):
            db_connection._connection_url()

    def test_redacts_encoded_and_plain_password(self):
        url = (
            "postgresql+psycopg2://postgres.project123:p%40ss%20word"
            "@pooler.example.com:5432/postgres?sslmode=require"
        )
        message = "failed p@ss word; dsn=" + url

        redacted = db_connection._redact(message, url)

        self.assertNotIn("p@ss word", redacted)
        self.assertNotIn("p%40ss%20word", redacted)
        self.assertIn("***", redacted)

    def test_engine_is_verified_with_select_one(self):
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        fake_url = "postgresql+psycopg2://dbuser:secret@db.example.com/app?sslmode=require"

        with (
            patch.object(db_connection, "_connection_url", return_value=(fake_url, {})),
            patch.object(db_connection, "create_engine", return_value=engine) as create,
            patch.object(db_connection, "_sync_latest_snapshot", return_value=None),
        ):
            result = db_connection.get_engine.__wrapped__()

        self.assertIs(result, engine)
        create.assert_called_once()
        connection.execute.assert_called_once()
        self.assertEqual(str(connection.execute.call_args.args[0]), "SELECT 1")


if __name__ == "__main__":
    unittest.main()
