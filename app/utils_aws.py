import boto3
import json
import os
from botocore.exceptions import ClientError, BotoCoreError

def upload_audit_report_to_s3(tenant_id, report_type, data):
    """
    Exporte le rapport d'audit vers le bucket S3 sécurisé (Chiffrement KMS / SSE-S3)
    """
    bucket_name = os.getenv('S3_BUCKET_NAME', 'saas-audit-reports-sec-2026-unique')
    region = os.getenv('AWS_REGION', 'us-east-1')
    
    try:
        s3_client = boto3.client('s3', region_name=region)
        
        file_name = f"tenants/{tenant_id}/reports/{report_type}_{tenant_id}.json"
        file_content = json.dumps(data, indent=4, default=str)

        s3_client.put_object(
            Bucket=bucket_name,
            Key=file_name,
            Body=file_content,
            ContentType='application/json',
            ServerSideEncryption='AES256'  # Chiffrement au repos côté serveur
        )
        return True, f"s3://{bucket_name}/{file_name}"
    except (ClientError, BotoCoreError, Exception) as e:
        # En mode Learner Lab ou hors ligne, on simule l'export proprement pour ne pas bloquer l'app
        print(f"[Avertissement AWS S3] : {e}")
        return False, str(e)
