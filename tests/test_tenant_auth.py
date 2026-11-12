import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import AuditLog, Iso27001Control, RgpdAudit, Tenant, User
from app.utils_aws import AuditExportResult


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
        self.assertIn(b'id="togglePassword"', response.data)
        self.assertIn(b'autocomplete="username"', response.data)
        self.assertIn(b'autocomplete="current-password"', response.data)

    def test_login_preserves_email_and_shows_generic_error(self):
        response = self.client.post(
            "/login",
            data={"email": "UNKNOWN@example.test", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="unknown@example.test"', response.data)
        self.assertIn(b"Identifiants invalides.", response.data)
        self.assertNotIn(b"UNKNOWN@example.test", response.data)
        with self.app.app_context():
            unknown_attempt = AuditLog.query.filter_by(action="auth.login").one()
            self.assertEqual(unknown_attempt.result, "failure")
            self.assertIsNone(unknown_attempt.tenant_id)
            self.assertIsNone(unknown_attempt.user_email)

        self.client.post(
            "/login",
            data={"email": "compliance@example.test", "password": "wrong-password"},
        )
        with self.app.app_context():
            known_attempt = AuditLog.query.filter_by(
                action="auth.login",
                tenant_id="tenant-a",
            ).one()
            self.assertEqual(known_attempt.result, "failure")
            self.assertEqual(known_attempt.user_email, "compliance@example.test")
            self.assertNotIn("wrong-password", known_attempt.action)

    def test_login_redirect_accepts_only_local_relative_targets(self):
        safe_response = self.client.post(
            "/login?next=%2Fiso27001",
            data={"email": "compliance@example.test", "password": "test-password"},
        )
        self.assertEqual(safe_response.status_code, 302)
        self.assertEqual(safe_response.headers["Location"], "/iso27001")

        self.client.post("/logout")
        for target in ("https://attacker.example", "//attacker.example", r"\\attacker.example"):
            with self.subTest(target=target):
                response = self.client.post(
                    "/login",
                    query_string={"next": target},
                    data={"email": "compliance@example.test", "password": "test-password"},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/")
                self.client.post("/logout")

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
        self.assertEqual(controls_response.get_json()[0]["status"], "Non démarré")

    def test_policies_dashboard_is_authenticated_and_tenant_scoped(self):
        response = self.client.get("/policies/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

        self.login()
        response = self.client.get("/policies/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tenant \xc2\xb7 tenant-a", response.data)
        self.assertIn(b"data-tenant-id=\"tenant-a\"", response.data)
        self.assertIn(b"TENANT_STORAGE_PREFIX + 'policies_state'", response.data)
        self.assertIn(b"/iso27001", response.data)
        self.assertIn(b"/rgpd/audit", response.data)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertIn(b"Brouillon", response.data)

    def test_iso_checklist_renders_catalog_filters_and_editor(self):
        self.login()
        response = self.client.get("/iso27001")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="catalog_id"', response.data)
        self.assertIn(b"A.5.1", response.data)
        self.assertIn(b'id="controlSearch"', response.data)
        self.assertIn(b'id="statusFilter"', response.data)
        self.assertIn(b'id="editControlDrawer"', response.data)
        self.assertIn(b"Progression pr\xc3\xa9visionnelle", response.data)
        self.assertNotIn(b'name="tenant_id"', response.data)

    def test_catalog_addition_and_duplicate_prevention_are_tenant_scoped(self):
        self.login()
        response = self.client.post(
            "/iso27001",
            data={
                "catalog_id": "A.5.1",
                "implementation_status": "En cours",
                "evidence_notes": "Politique interne en préparation",
            },
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/iso27001",
            data={"catalog_id": "A.5.1", "implementation_status": "Non démarré"},
        )
        self.assertEqual(response.status_code, 409)

        with self.app.app_context():
            control = Iso27001Control.query.filter_by(
                tenant_id="tenant-a",
                control_domain="A.5.1 — Organisationnel",
            ).one()
            self.assertEqual(control.control_title, "Politique de sécurité de l’information")
            self.assertEqual(control.implementation_status, "En cours")
            self.assertEqual(control.company_name, "tenant-a")
            self.assertEqual(
                Iso27001Control.query.filter_by(
                    tenant_id="tenant-b",
                    control_domain="A.5.1 — Organisationnel",
                ).count(),
                0,
            )

        self.assertEqual(
            self.client.post(
                "/iso27001",
                data={"catalog_id": "A.999", "implementation_status": "Non démarré"},
            ).status_code,
            400,
        )

    def test_iso_edit_is_tenant_scoped_and_validates_status(self):
        self.login()
        response = self.client.post(
            "/iso27001/1/edit",
            data={
                "implementation_status": "Implémenté",
                "evidence_notes": "Procédure validée",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.post(
                "/iso27001/2/edit",
                data={"implementation_status": "Implémenté"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/iso27001/1/edit",
                data={"implementation_status": "falsified"},
            ).status_code,
            400,
        )

        with self.app.app_context():
            control = db.session.get(Iso27001Control, 1)
            self.assertEqual(control.tenant_id, "tenant-a")
            self.assertEqual(control.implementation_status, "Implémenté")
            self.assertEqual(control.evidence_notes, "Procédure validée")

    def test_iso_progress_excludes_non_applicable_controls(self):
        self.login()
        response = self.client.post(
            "/iso/checklist",
            json={
                "controls": [
                    {"status": "Implémenté"},
                    {"status": "En cours"},
                    {"status": "Non applicable"},
                ]
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["controls_checked"], 3)
        self.assertEqual(response.get_json()["controls_implemented"], 1)
        self.assertEqual(response.get_json()["compliance_score"], "50.0%")

        empty_response = self.client.post("/iso/checklist", json={"controls": []})
        self.assertEqual(empty_response.status_code, 201)
        self.assertEqual(empty_response.get_json()["controls_checked"], 0)
        self.assertEqual(empty_response.get_json()["compliance_score"], "0.0%")

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

        failed_export = AuditExportResult(False, "local-copy.json", None, "AccessDenied")
        with patch("app.routes_rgpd.upload_audit_report_to_s3", return_value=failed_export):
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
        self.assertEqual(response.get_json()["status"], "partial")
        self.assertFalse(response.get_json()["s3_storage"]["uploaded_to_aws"])
        self.assertEqual(response.get_json()["s3_storage"]["error"], "AccessDenied")

        with patch("app.routes_policies.upload_audit_report_to_s3", return_value=failed_export):
            response = self.client.post(
                "/policies/generate",
                json={"tenant_id": "tenant-b", "user_email": "forged@example.test"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["tenant_id"], "tenant-a")
        self.assertEqual(response.get_json()["status"], "partial")
        self.assertFalse(response.get_json()["s3_storage"]["uploaded_to_aws"])

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
                7,
            )
            self.assertEqual(
                AuditLog.query.filter_by(user_email="forged@example.test").count(),
                0,
            )
            self.assertEqual(
                AuditLog.query.filter_by(action="s3.export", result="failure").count(),
                2,
            )
            self.assertEqual(
                AuditLog.query.filter_by(action="iso27001.control.create", result="success").count(),
                2,
            )
            self.assertEqual(
                AuditLog.query.filter_by(action="security_policy.generate", result="success").count(),
                1,
            )

    def test_auditor_is_read_only(self):
        self.login("auditor@example.test")
        self.assertEqual(self.client.get("/policies/").status_code, 403)
        dashboard = self.client.get("/iso27001")
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotIn(b'id="catalog_id"', dashboard.data)
        self.assertNotIn(b'id="editControlDrawer"', dashboard.data)

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
