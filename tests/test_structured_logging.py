import io
import json
import logging
import re
import unittest

from app import create_app
from flask import abort
from sqlalchemy.exc import SQLAlchemyError


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
        for log_filter in original_handlers[0].filters:
            handler.addFilter(log_filter)
        logger.handlers = [handler]

        try:
            response = app.test_client().get(
                "/login?token=must-not-be-logged",
                headers={"X-Request-ID": "client-supplied-id"},
            )
        finally:
            logger.handlers = original_handlers
            handler.close()

        self.assertEqual(response.status_code, 200)
        request_id = response.headers["X-Request-ID"]
        self.assertRegex(request_id, re.compile(r"^[0-9a-f]{32}$"))
        self.assertNotEqual(request_id, "client-supplied-id")
        log_entry = json.loads(output.getvalue())
        self.assertEqual(log_entry["event"], "http.request.completed")
        self.assertEqual(log_entry["request_id"], request_id)
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
        for log_filter in original_handlers[0].filters:
            handler.addFilter(log_filter)
        logger.handlers = [handler]

        try:
            response = app.test_client().get("/not-found/private-token")
        finally:
            logger.handlers = original_handlers
            handler.close()

        self.assertEqual(response.status_code, 404)
        request_id = response.headers["X-Request-ID"]
        log_entry = json.loads(output.getvalue())
        self.assertEqual(log_entry["request_id"], request_id)
        self.assertEqual(log_entry["endpoint"], "unmatched")
        self.assertEqual(log_entry["status_code"], 404)
        self.assertNotIn("/not-found", output.getvalue())
        self.assertNotIn("private-token", output.getvalue())

    def test_application_logs_share_response_request_id(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )

        @app.get("/_test/request-correlation")
        def emit_application_log():
            app.logger.info("Test application event", extra={"event": "test.application"})
            return "ok"

        logger = app.logger
        original_handlers = logger.handlers
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(original_handlers[0].formatter)
        for log_filter in original_handlers[0].filters:
            handler.addFilter(log_filter)
        logger.handlers = [handler]

        try:
            response = app.test_client().get("/_test/request-correlation")
        finally:
            logger.handlers = original_handlers
            handler.close()

        self.assertEqual(response.status_code, 200)
        request_id = response.headers["X-Request-ID"]
        log_entries = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(log_entries), 2)
        self.assertEqual(
            [entry["request_id"] for entry in log_entries],
            [request_id, request_id],
        )
        self.assertEqual(log_entries[0]["event"], "test.application")
        self.assertEqual(log_entries[1]["event"], "http.request.completed")

    def test_denial_and_database_error_are_logged_without_exception_details(self):
        app = create_app(
            {
                "TESTING": True,
                "PROPAGATE_EXCEPTIONS": False,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )

        @app.get("/_test/forbidden")
        def deny_request():
            abort(403)

        @app.get("/_test/database-error")
        def raise_database_error():
            raise SQLAlchemyError("sensitive database details")

        logger = app.logger
        original_handlers = logger.handlers
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(original_handlers[0].formatter)
        for log_filter in original_handlers[0].filters:
            handler.addFilter(log_filter)
        logger.handlers = [handler]

        try:
            client = app.test_client()
            denied_response = client.get("/_test/forbidden")
            error_response = client.get("/_test/database-error")
        finally:
            logger.handlers = original_handlers
            handler.close()

        entries = [json.loads(line) for line in output.getvalue().splitlines()]
        denied = next(
            entry
            for entry in entries
            if entry.get("event") == "security.authorization.denied"
        )
        database_error = next(
            entry
            for entry in entries
            if entry.get("event") == "application.exception"
        )
        self.assertEqual(denied_response.status_code, 403)
        self.assertEqual(denied["request_id"], denied_response.headers["X-Request-ID"])
        self.assertEqual(denied["outcome"], "denied")
        self.assertEqual(error_response.status_code, 500)
        self.assertEqual(database_error["request_id"], error_response.headers["X-Request-ID"])
        self.assertEqual(database_error["error_category"], "database")
        self.assertEqual(database_error["error_type"], "SQLAlchemyError")
        self.assertNotIn("sensitive database details", output.getvalue())
        self.assertNotIn("/_test/database-error", output.getvalue())


if __name__ == "__main__":
    unittest.main()
