import io
import json
import logging
import unittest

from app import create_app


class StructuredLoggingTests(unittest.TestCase):
    def test_http_request_log_is_json_and_excludes_query_string(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        logger = app.logger
        original_handlers = logger.handlers
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(original_handlers[0].formatter)
        logger.handlers = [handler]

        try:
            response = app.test_client().get("/login?token=must-not-be-logged")
        finally:
            logger.handlers = original_handlers
            handler.close()

        self.assertEqual(response.status_code, 200)
        log_entry = json.loads(output.getvalue())
        self.assertEqual(log_entry["event"], "http.request.completed")
        self.assertEqual(log_entry["http_method"], "GET")
        self.assertEqual(log_entry["endpoint"], "login")
        self.assertEqual(log_entry["status_code"], 200)
        self.assertGreaterEqual(log_entry["duration_ms"], 0)
        self.assertTrue(log_entry["timestamp"].endswith("Z"))
        self.assertNotIn("must-not-be-logged", output.getvalue())
        self.assertNotIn("/login?", output.getvalue())

    def test_unmatched_route_is_logged_without_request_path(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        logger = app.logger
        original_handlers = logger.handlers
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(original_handlers[0].formatter)
        logger.handlers = [handler]

        try:
            response = app.test_client().get("/not-found/private-token")
        finally:
            logger.handlers = original_handlers
            handler.close()

        self.assertEqual(response.status_code, 404)
        log_entry = json.loads(output.getvalue())
        self.assertEqual(log_entry["endpoint"], "unmatched")
        self.assertEqual(log_entry["status_code"], 404)
        self.assertNotIn("/not-found", output.getvalue())
        self.assertNotIn("private-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
