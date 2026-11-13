import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, NoCredentialsError

from app import create_app, db
from app.audit_export import export_pending_audit_logs
from app.models import AuditLog
from app.utils_aws import (
    AuditExportResult,
    upload_audit_report_to_s3,
    upload_generated_export,
    verify_s3_bucket_security,
)


class AuditExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "S3_BUCKET_NAME": "test-audit-bucket",
                "AWS_REGION": "us-east-1",
                "AUDIT_EXPORT_DIR": self.temp_dir.name,
            }
        )
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def test_upload_keeps_unique_local_copies_and_confirms_encryption(self):
        client = Mock()
        client.put_object.return_value = {"ServerSideEncryption": "AES256"}
        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=client
        ):
            first = upload_audit_report_to_s3("tenant-a", "audit", {"value": 1})
            second = upload_audit_report_to_s3("tenant-a", "audit", {"value": 2})

        self.assertTrue(first.uploaded)
        self.assertTrue(second.uploaded)
        self.assertNotEqual(first.local_path, second.local_path)
        self.assertTrue(Path(first.local_path).is_file())
        self.assertTrue(Path(second.local_path).is_file())
        self.assertIn("tenants/tenant-a/reports/", first.s3_uri)
        self.assertEqual(client.put_object.call_args.kwargs["ServerSideEncryption"], "AES256")

    def test_generated_csv_export_keeps_local_copy_and_uploads_tenant_scoped_bytes(self):
        client = Mock()
        client.put_object.return_value = {"ServerSideEncryption": "AES256"}
        content = b"\xef\xbb\xbfheader,value\r\n"

        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=client
        ):
            result = upload_generated_export(
                "tenant-a",
                "rgpd_audit_browser_csv",
                "csv",
                content,
            )

        self.assertTrue(result.uploaded)
        self.assertTrue(Path(result.local_path).is_file())
        self.assertEqual(Path(result.local_path).read_bytes(), content)
        self.assertIn("tenants/tenant-a/reports/", result.s3_uri)
        self.assertEqual(client.put_object.call_args.kwargs["Body"], content)
        self.assertEqual(client.put_object.call_args.kwargs["ContentType"], "text/csv; charset=utf-8")
        self.assertEqual(client.put_object.call_args.kwargs["ServerSideEncryption"], "AES256")

    def test_retryable_s3_failure_is_retried_and_access_denied_is_not(self):
        throttled = ClientError({"Error": {"Code": "SlowDown"}}, "PutObject")
        client = Mock()
        client.put_object.side_effect = [
            throttled,
            throttled,
            {"ServerSideEncryption": "AES256"},
        ]
        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=client
        ), patch("app.utils_aws.time.sleep"):
            result = upload_audit_report_to_s3("tenant-a", "audit", {"value": 1})
        self.assertTrue(result.uploaded)
        self.assertEqual(client.put_object.call_count, 3)

        denied_client = Mock()
        denied_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "PutObject"
        )
        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=denied_client
        ), patch("app.utils_aws.time.sleep") as sleep:
            denied = upload_audit_report_to_s3("tenant-a", "audit", {"value": 1})
        self.assertFalse(denied.uploaded)
        self.assertEqual(denied.error, "S3 upload failed (AccessDenied).")
        self.assertTrue(Path(denied.local_path).is_file())
        self.assertEqual(denied_client.put_object.call_count, 1)
        sleep.assert_not_called()

    def test_missing_aws_credentials_keeps_local_copy_and_reports_failure(self):
        client = Mock()
        client.put_object.side_effect = NoCredentialsError()
        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=client
        ):
            result = upload_audit_report_to_s3("tenant-a", "audit", {"value": 1})

        self.assertFalse(result.uploaded)
        self.assertIn("credentials are unavailable", result.error)
        self.assertTrue(Path(result.local_path).is_file())
        client.put_object.assert_called_once()

    def test_bucket_verification_checks_public_access_and_default_encryption(self):
        client = Mock()
        client.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
        client.get_bucket_policy_status.return_value = {
            "PolicyStatus": {"IsPublic": False}
        }
        client.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            }
        }
        with self.app.app_context(), patch(
            "app.utils_aws.boto3.client", return_value=client
        ):
            checks = verify_s3_bucket_security()

        self.assertTrue(checks["secure"])
        client.get_bucket_encryption.assert_called_once_with(Bucket="test-audit-bucket")

    def test_incremental_export_advances_only_after_success(self):
        payloads = []

        def fake_upload(tenant_id, report_type, data):
            payloads.append(data)
            return AuditExportResult(True, "local.json", "s3://bucket/key")

        with self.app.app_context():
            db.session.add(
                AuditLog(
                    tenant_id="tenant-a",
                    user_email="actor@example.test",
                    action="iso27001.control.update",
                    result="success",
                )
            )
            db.session.commit()
            with patch("app.audit_export.upload_audit_report_to_s3", side_effect=fake_upload):
                first = export_pending_audit_logs()
                second = export_pending_audit_logs()

        self.assertEqual(len(first), 1)
        self.assertTrue(first[0]["uploaded"])
        self.assertEqual(len(payloads[0]["records"]), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(
            [record["action"] for record in payloads[1]["records"]],
            ["audit.export"],
        )
        self.assertTrue(payloads[0]["records"][0]["timestamp_utc"].endswith("+00:00"))

    def test_export_cli_returns_failure_and_audits_the_failed_attempt(self):
        with self.app.app_context():
            db.session.add(
                AuditLog(
                    tenant_id="tenant-a",
                    user_email="actor@example.test",
                    action="auth.login",
                    result="success",
                )
            )
            db.session.commit()

        with patch(
            "app.audit_export.upload_audit_report_to_s3",
            return_value=AuditExportResult(
                False,
                "local.json",
                None,
                "S3 upload failed (AccessDenied).",
            ),
        ):
            result = self.app.test_cli_runner().invoke(args=["export-audit-logs"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("AccessDenied", result.output)
        with self.app.app_context():
            failed_export = AuditLog.query.filter_by(action="audit.export").one()
            self.assertEqual(failed_export.result, "failure")
