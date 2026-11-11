import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import AuditLog, Iso27001Control, RgpdAudit, Tenant, User


class TenantAuthTests(unittest.TestCase):
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
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Tenant(id="tenant-a", name="Tenant A"),
                    Tenant(id="tenant-b", name="Tenant B"),
                ]
            )
            compliance_user = User(email="compliance@example.test", role="compliance", tenant_id="tenant-a")
            compliance_user.set_password("test-password")
            auditor = User(email="auditor@example.test", role="auditor", tenant_id="tenant-a")
            auditor.set_password("test-password")
            db.session.add_all([compliance_user, auditor])
            db.session.add_all(
                [
                    RgpdAudit(
                        tenant_id="tenant-a",
                        company_name="A",
                        data_processing_name="Audit A",
                    ),
                    RgpdAudit(
                        tenant_id="tenant-b",
                        company_name="B",
                        data_processing_name="Audit B",
                    ),
                    Iso27001Control(
                        tenant_id="tenant-a",
                        company_name="A",
                        control_domain="A.5",
                        control_title="Control A",
                    ),
                    Iso27001Control(
                        tenant_id="tenant-b",
                        company_name="B",
                        control_domain="A.6",
                        control_title="Control B",
                    ),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self, email="compliance@example.test"):
        return self.client.post(
            "/login",
            data={"email": email, "password": "test-password"},
        )

    def test_authentication_is_required(self):
        for path in ("/", "/rgpd/audit", "/rgpd/audits", "/iso27001", "/controls"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])

    def test_login_form_contains_csrf_token(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf_token"', response.data)

    def test_operator_cli_creates_tenant_scoped_user(self):
        result = self.app.test_cli_runner().invoke(
            args=[
                "create-user",
                "--email",
                "new-admin@example.test",
                "--tenant-id",
                "tenant-cli",
                "--role",
                "admin",
            ],
            input="Strong-Test-Password\nStrong-Test-Password\n",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            user = User.query.filter_by(email="new-admin@example.test").one()
            self.assertEqual(user.tenant_id, "tenant-cli")
            self.assertEqual(user.role, "admin")
            self.assertTrue(user.check_password("Strong-Test-Password"))

    def test_reads_are_scoped_to_logged_in_tenant(self):
        self.login()

        rgpd_response = self.client.get("/rgpd/audits?tenant_id=tenant-b")
        self.assertEqual(rgpd_response.status_code, 200)
        rgpd_data = rgpd_response.get_json()
        self.assertEqual(rgpd_data["tenant_id"], "tenant-a")
        self.assertEqual([audit["processing_name"] for audit in rgpd_data["audits"]], ["Audit A"])
        self.assertEqual(self.client.get("/rgpd/audits/tenant-b").status_code, 404)

        rgpd_page = self.client.get("/rgpd/audit")
        self.assertEqual(rgpd_page.status_code, 200)
        self.assertIn(
            b"const STORAGE_KEY = 'audit_rgpd_state:' + \"tenant-a\";",
            rgpd_page.data,
        )

        dashboard_response = self.client.get("/iso27001?tenant_id=tenant-b")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(b"Control A", dashboard_response.data)
        self.assertNotIn(b"Control B", dashboard_response.data)

        controls_response = self.client.get("/controls?tenant_id=tenant-b")
        self.assertEqual(controls_response.status_code, 200)
        self.assertEqual([item["name"] for item in controls_response.get_json()], ["Control A"])

    def test_writes_ignore_tenant_ids_supplied_by_client(self):
        self.login()

        response = self.client.post(
            "/iso27001",
            data={
                "tenant_id": "tenant-b",
                "company_name": "A",
                "control_domain": "A.7",
                "control_title": "Added by form",
                "implementation_status": "Partiel",
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/controls",
            json={"tenant_id": "tenant-b", "name": "Added by API"},
        )
        self.assertEqual(response.status_code, 201)

        with patch("app.routes_rgpd.upload_audit_report_to_s3", return_value=(False, "unavailable")):
            response = self.client.post(
                "/rgpd/audit",
                json={
                    "tenant_id": "tenant-b",
                    "user_email": "forged@example.test",
                    "company_name": "A",
                    "processing_name": "New audit",
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["tenant_id"], "tenant-a")

        with patch("app.routes_policies.upload_audit_report_to_s3", return_value=(False, "unavailable")):
            response = self.client.post(
                "/policies/generate",
                json={"tenant_id": "tenant-b", "user_email": "forged@example.test"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["tenant_id"], "tenant-a")

        self.assertEqual(
            self.client.post("/controls", json={"name": "Bad", "status": []}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/policies/generate", json={"policy_type": []}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/rgpd/audit", json={"processing_name": []}).status_code,
            400,
        )

        with self.app.app_context():
            self.assertEqual(
                Iso27001Control.query.filter_by(tenant_id="tenant-b").count(),
                1,
            )
            self.assertEqual(
                Iso27001Control.query.filter_by(tenant_id="tenant-a").count(),
                3,
            )
            self.assertEqual(
                RgpdAudit.query.filter_by(tenant_id="tenant-a", data_processing_name="New audit").count(),
                1,
            )
            self.assertEqual(
                AuditLog.query.filter_by(tenant_id="tenant-a", user_email="compliance@example.test").count(),
                2,
            )
            self.assertEqual(
                AuditLog.query.filter_by(user_email="forged@example.test").count(),
                0,
            )

    def test_auditor_is_read_only(self):
        self.login("auditor@example.test")
        write_requests = (
            ("/iso27001", {}),
            ("/controls", {"json": {"name": "Forbidden"}}),
            ("/iso/checklist", {"json": {"controls": []}}),
            ("/rgpd/audit", {"json": {"processing_name": "Forbidden"}}),
            ("/policies/generate", {"json": {"policy_type": "password_policy"}}),
        )
        for path, kwargs in write_requests:
            with self.subTest(path=path):
                response = self.client.post(path, **kwargs)
                self.assertEqual(response.status_code, 403)

    def test_csrf_is_required_for_state_changing_requests(self):
        csrf_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": True,
            }
        )
        client = csrf_app.test_client()
        with csrf_app.app_context():
            db.create_all()
            tenant = Tenant(id="tenant-a", name="Tenant A")
            user = User(email="csrf@example.test", role="compliance", tenant_id="tenant-a")
            user.set_password("test-password")
            db.session.add_all([tenant, user])
            db.session.commit()
            user_id = user.id

        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        response = client.post("/policies/generate", json={"policy_type": "password_policy"})
        self.assertEqual(response.status_code, 400)
        with csrf_app.app_context():
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
