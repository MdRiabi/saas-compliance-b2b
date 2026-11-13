import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect

from app import create_app, db


class MigrationTests(unittest.TestCase):
    def test_upgrade_creates_application_tables_on_a_fresh_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir, "fresh.sqlite")
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "test-only-secret",
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///" + database_path.as_posix(),
                    "WTF_CSRF_ENABLED": False,
                }
            )

            result = app.test_cli_runner().invoke(args=["db", "upgrade"])
            self.assertEqual(result.exit_code, 0, result.output)

            with app.app_context():
                inspector = inspect(db.engine)
                self.assertTrue(
                    {
                        "audit_log",
                        "tenants",
                        "users",
                        "rgpd_audit",
                        "iso27001_control",
                    }.issubset(inspector.get_table_names())
                )
                user_columns = {column["name"] for column in inspector.get_columns("users")}
                self.assertIn("mfa_enabled", user_columns)
                self.assertIn("mfa_last_verified_step", user_columns)

            response = app.test_client().post(
                "/login",
                data={"email": "missing@example.test", "password": "irrelevant"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Identifiants invalides.", response.data)
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
