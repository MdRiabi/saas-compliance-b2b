import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ConnectionClosedError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from flask import current_app


_RETRYABLE_S3_CODES = {
    "InternalError",
    "RequestTimeout",
    "ServiceUnavailable",
    "SlowDown",
    "500",
    "503",
}
_RETRYABLE_CONNECTION_ERRORS = (
    ConnectTimeoutError,
    ConnectionClosedError,
    EndpointConnectionError,
    ReadTimeoutError,
)
_MAX_UPLOAD_ATTEMPTS = 3


@dataclass(frozen=True)
class AuditExportResult:
    uploaded: bool
    local_path: Optional[str]
    s3_uri: Optional[str]
    error: Optional[str] = None


def _safe_path_component(value):
    component = quote(str(value), safe="")
    return f"_{component}" if component in {".", ".."} else component


def _error_code(error):
    return error.response.get("Error", {}).get("Code", "S3ClientError")


def _local_export_path(tenant_id, report_type, data):
    root = Path(
        current_app.config.get("AUDIT_EXPORT_DIR")
        or Path(current_app.instance_path) / "audit_exports"
    )
    tenant_component = _safe_path_component(tenant_id or "unassigned")
    report_component = re.sub(r"[^A-Za-z0-9_-]+", "_", str(report_type)).strip("_")
    report_component = report_component[:64] or "report"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{report_component}_{timestamp}_{uuid.uuid4().hex}.json"
    tenant_dir = root / tenant_component
    target_dir = tenant_dir / "reports"
    target_path = target_dir / filename
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    created = False
    try:
        tenant_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target_dir.mkdir(mode=0o700, exist_ok=True)
        if os.name != "nt":
            tenant_dir.chmod(0o700)
            target_dir.chmod(0o700)
        descriptor = os.open(
            target_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "wb") as export_file:
            export_file.write(payload)
    except OSError as error:
        local_path = str(target_path) if created and target_path.is_file() else None
        return local_path, f"Local archive failed ({type(error).__name__})."
    return target_path, None


def _local_export_file_path(tenant_id, report_type, extension, content):
    root = Path(
        current_app.config.get("AUDIT_EXPORT_DIR")
        or Path(current_app.instance_path) / "audit_exports"
    )
    tenant_component = _safe_path_component(tenant_id or "unassigned")
    report_component = re.sub(r"[^A-Za-z0-9_-]+", "_", str(report_type)).strip("_")
    report_component = report_component[:64] or "export"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{report_component}_{timestamp}_{uuid.uuid4().hex}.{extension}"
    tenant_dir = root / tenant_component
    target_dir = tenant_dir / "reports"
    target_path = target_dir / filename

    created = False
    try:
        tenant_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target_dir.mkdir(mode=0o700, exist_ok=True)
        if os.name != "nt":
            tenant_dir.chmod(0o700)
            target_dir.chmod(0o700)
        descriptor = os.open(
            target_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "wb") as export_file:
            export_file.write(content)
    except OSError as error:
        local_path = str(target_path) if created and target_path.is_file() else None
        return local_path, f"Local archive failed ({type(error).__name__})."
    return target_path, None


def _upload_local_file_to_s3(tenant_id, local_path, content_type, payload):
    bucket_name = current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        return AuditExportResult(
            False,
            str(local_path),
            None,
            "S3_BUCKET_NAME is not configured.",
        )

    region = (
        current_app.config.get("AWS_REGION")
        or os.getenv("AWS_REGION")
        or "us-east-1"
    )
    encryption = (
        current_app.config.get("S3_SERVER_SIDE_ENCRYPTION")
        or os.getenv("S3_SERVER_SIDE_ENCRYPTION")
        or "AES256"
    )
    if encryption not in {"AES256", "aws:kms"}:
        return AuditExportResult(
            False,
            str(local_path),
            None,
            "S3_SERVER_SIDE_ENCRYPTION must be AES256 or aws:kms.",
        )

    tenant_component = _safe_path_component(tenant_id or "unassigned")
    key = f"tenants/{tenant_component}/reports/{local_path.name}"
    s3_uri = f"s3://{bucket_name}/{key}"
    request = {
        "Bucket": bucket_name,
        "Key": key,
        "Body": payload,
        "ContentType": content_type,
        "ServerSideEncryption": encryption,
    }
    if encryption == "aws:kms":
        kms_key_id = current_app.config.get("S3_KMS_KEY_ID") or os.getenv("S3_KMS_KEY_ID")
        if kms_key_id:
            request["SSEKMSKeyId"] = kms_key_id

    s3_client = boto3.client("s3", region_name=region)
    for attempt in range(_MAX_UPLOAD_ATTEMPTS):
        try:
            response = s3_client.put_object(**request)
            if response.get("ServerSideEncryption") != encryption:
                return AuditExportResult(
                    False,
                    str(local_path),
                    None,
                    "S3 did not confirm the requested server-side encryption.",
                )
            return AuditExportResult(True, str(local_path), s3_uri)
        except ClientError as error:
            code = _error_code(error)
            if code not in _RETRYABLE_S3_CODES or attempt == _MAX_UPLOAD_ATTEMPTS - 1:
                return AuditExportResult(
                    False,
                    str(local_path),
                    None,
                    f"S3 upload failed ({code}).",
                )
        except NoCredentialsError:
            return AuditExportResult(
                False,
                str(local_path),
                None,
                "AWS credentials are unavailable in the configured credential chain.",
            )
        except _RETRYABLE_CONNECTION_ERRORS as error:
            if attempt == _MAX_UPLOAD_ATTEMPTS - 1:
                return AuditExportResult(
                    False,
                    str(local_path),
                    None,
                    f"S3 connection failed ({type(error).__name__}).",
                )
        except BotoCoreError as error:
            return AuditExportResult(
                False,
                str(local_path),
                None,
                f"AWS request could not be completed ({type(error).__name__}).",
            )

        time.sleep(0.25 * (2**attempt))

    raise RuntimeError("S3 retry loop ended unexpectedly.")


def upload_audit_report_to_s3(tenant_id, report_type, data):
    """Keep a unique local copy, then upload it with explicit server-side encryption."""
    local_path, local_error = _local_export_path(tenant_id, report_type, data)
    if local_error:
        return AuditExportResult(False, None, None, local_error)

    return _upload_local_file_to_s3(
        tenant_id,
        local_path,
        "application/json",
        local_path.read_bytes(),
    )


def upload_generated_export(tenant_id, report_type, file_format, content):
    """Keep a private local copy and upload a generated browser export to S3."""
    formats = {
        "json": ("json", "application/json"),
        "csv": ("csv", "text/csv; charset=utf-8"),
        "pdf": ("pdf", "application/pdf"),
    }
    if file_format not in formats or not re.fullmatch(r"[a-z0-9_-]{1,64}", report_type):
        raise ValueError("Unsupported export format or report type.")
    if not isinstance(content, bytes):
        raise TypeError("Export content must be bytes.")

    extension, content_type = formats[file_format]
    local_path, local_error = _local_export_file_path(
        tenant_id,
        report_type,
        extension,
        content,
    )
    if local_error:
        return AuditExportResult(False, local_path, None, local_error)
    return _upload_local_file_to_s3(
        tenant_id,
        local_path,
        content_type,
        content,
    )


def verify_s3_bucket_security():
    bucket_name = current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME is not configured.")
    region = (
        current_app.config.get("AWS_REGION")
        or os.getenv("AWS_REGION")
        or "us-east-1"
    )
    s3_client = boto3.client("s3", region_name=region)

    try:
        public_access = s3_client.get_public_access_block(Bucket=bucket_name).get(
            "PublicAccessBlockConfiguration", {}
        )
    except ClientError as error:
        if _error_code(error) != "NoSuchPublicAccessBlockConfiguration":
            raise
        public_access = {}
    try:
        policy_status = s3_client.get_bucket_policy_status(Bucket=bucket_name)
    except ClientError as error:
        if _error_code(error) != "NoSuchBucketPolicy":
            raise
        policy_status = {"PolicyStatus": {"IsPublic": False}}
    try:
        encryption = s3_client.get_bucket_encryption(Bucket=bucket_name)
    except ClientError as error:
        if _error_code(error) != "ServerSideEncryptionConfigurationNotFoundError":
            raise
        encryption = {}
    encryption_algorithms = {
        rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        for rule in encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    }
    public_block_enabled = all(
        public_access.get(setting) is True
        for setting in (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
    )
    encryption_enabled = bool(encryption_algorithms & {"AES256", "aws:kms", "aws:kms:dsse"})
    bucket_private = public_block_enabled and not policy_status.get("PolicyStatus", {}).get(
        "IsPublic", True
    )
    return {
        "bucket": bucket_name,
        "public_access_block_enabled": public_block_enabled,
        "bucket_policy_is_public": policy_status.get("PolicyStatus", {}).get("IsPublic"),
        "default_encryption_enabled": encryption_enabled,
        "encryption_algorithms": sorted(algorithm for algorithm in encryption_algorithms if algorithm),
        "private": bucket_private,
        "secure": bucket_private and encryption_enabled,
    }
