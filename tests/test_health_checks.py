import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db


class HealthCheckTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

    def test_liveness_is_available_without_database_access(self):
        with self.app.app_context(), patch.object(
            db.engine,
            "connect",
            side_effect=SQLAlchemyError("database unavailable"),
        ):
            response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "alive"})

    def test_readiness_succeeds_when_database_is_available(self):
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ready"})

    def test_readiness_returns_generic_unavailable_response_on_database_error(self):
        with self.app.app_context(), patch.object(
            db.engine,
            "connect",
            side_effect=SQLAlchemyError("private database details"),
        ):
            response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "unavailable"})
        self.assertNotIn(b"private database details", response.data)


if __name__ == "__main__":
    unittest.main()
