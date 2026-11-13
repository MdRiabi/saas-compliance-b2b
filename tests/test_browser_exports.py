import json
import re
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import AuditLog, Tenant, User
from app.utils_aws import AuditExportResult


class BrowserExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
                "AUDIT_EXPORT_DIR": self.temp_dir.name,
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            tenant = Tenant(id="tenant-a", name="Tenant A")
            compliance = User(
                email="compliance@example.test",
                role="compliance",
                tenant_id="tenant-a",
            )
            compliance.set_password("test-password")
            auditor = User(
                email="auditor@example.test",
                role="auditor",
                tenant_id="tenant-a",
            )
            auditor.set_password("test-password")
            db.session.add_all([tenant, compliance, auditor])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def login(self, email="compliance@example.test"):
        return self.client.post(
            "/login",
            data={"email": email, "password": "test-password"},
        )

    def test_audit_json_export_uses_authenticated_tenant(self):
        self.login()
        content = json.dumps({"tenant_id": "forged-tenant", "report": "audit"})
        with patch(
            "app.routes_exports.upload_generated_export",
            return_value=AuditExportResult(
                True,
                "local.json",
                "s3://test-bucket/tenants/tenant-a/reports/export.json",
            ),
        ) as upload:
            response = self.client.post(
                "/exports/audit/json",
                json={"content": content},
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["s3_storage"]["local_copy_retained"])
        self.assertNotIn("local.json", response.get_data(as_text=True))
        self.assertEqual(upload.call_args.args[0], "tenant-a")
        self.assertEqual(upload.call_args.args[1], "rgpd_audit_browser_json")
        self.assertEqual(upload.call_args.args[2], "json")
        self.assertEqual(upload.call_args.args[3], content.encode("utf-8"))
        with self.app.app_context():
            event = AuditLog.query.filter_by(action="s3.export").one()
            self.assertEqual(event.tenant_id, "tenant-a")
            self.assertEqual(event.result, "success")

    def test_pdf_export_generates_pdf_before_upload(self):
        self.login()
        with patch(
            "app.routes_exports.upload_generated_export",
            return_value=AuditExportResult(
                True,
                "local.pdf",
                "s3://test-bucket/tenants/tenant-a/reports/export.pdf",
            ),
        ) as upload:
            response = self.client.post(
                "/exports/policies/pdf",
                json={"html": "<h1>Pack sécurité</h1><p>Version démonstration.</p>"},
            )

        self.assertEqual(response.status_code, 201)
        content = upload.call_args.args[3]
        self.assertTrue(content.startswith(b"%PDF-"))

    def test_auditor_can_export_audit_but_cannot_export_policies(self):
        self.login("auditor@example.test")
        with patch(
            "app.routes_exports.upload_generated_export",
            return_value=AuditExportResult(True, "local.csv", "s3://bucket/key"),
        ) as upload:
            audit_response = self.client.post(
                "/exports/audit/csv",
                json={"content": "header,value\n"},
            )
            policies_response = self.client.post(
                "/exports/policies/csv",
                json={"content": "header,value\n"},
            )

        self.assertEqual(audit_response.status_code, 201)
        self.assertEqual(policies_response.status_code, 403)
        upload.assert_called_once()

    def test_invalid_export_content_and_s3_failure_are_explicit(self):
        self.login()
        invalid_json = self.client.post(
            "/exports/audit/json",
            json={"content": "{invalid"},
        )
        self.assertEqual(invalid_json.status_code, 400)

        with patch(
            "app.routes_exports.upload_generated_export",
            return_value=AuditExportResult(
                False,
                "local.csv",
                None,
                "S3 upload failed (AccessDenied).",
            ),
        ):
            failed_upload = self.client.post(
                "/exports/audit/csv",
                json={"content": "header,value\n"},
            )

        self.assertEqual(failed_upload.status_code, 502)
        self.assertEqual(
            failed_upload.get_json()["s3_storage"]["error"],
            "S3 upload failed (AccessDenied).",
        )
        with self.app.app_context():
            event = AuditLog.query.filter_by(action="s3.export", result="failure").one()
            self.assertEqual(event.tenant_id, "tenant-a")

    def test_export_endpoint_requires_csrf_token(self):
        csrf_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "csrf-test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": True,
            }
        )
        client = csrf_app.test_client()
        with csrf_app.app_context():
            db.create_all()
            tenant = Tenant(id="tenant-csrf", name="Tenant CSRF")
            user = User(
                email="csrf@example.test",
                role="compliance",
                tenant_id="tenant-csrf",
            )
            user.set_password("test-password")
            db.session.add_all([tenant, user])
            db.session.commit()
            user_id = user.id

        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        page = client.get("/rgpd/audit")
        self.assertEqual(page.status_code, 200)
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data)
        self.assertIsNotNone(match)

        request_data = {"content": json.dumps({"report": "audit"})}
        without_token = client.post("/exports/audit/json", json=request_data)
        self.assertEqual(without_token.status_code, 400)
        with patch(
            "app.routes_exports.upload_generated_export",
            return_value=AuditExportResult(True, "local.json", "s3://bucket/key"),
        ):
            with_token = client.post(
                "/exports/audit/json",
                json=request_data,
                headers={"X-CSRFToken": match.group(1).decode("ascii")},
            )
        self.assertEqual(with_token.status_code, 201)

        with csrf_app.app_context():
            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
