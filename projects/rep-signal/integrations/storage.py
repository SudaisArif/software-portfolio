"""Optional private R2/S3 adapter with SHA-256 metadata verification.

Requires boto3 only for live operations. Presigned read URLs are bearer secrets;
store them only in the ignored data directory and never log them.
"""
import hashlib
import os
import time
from pathlib import Path
from .http import IntegrationBlocked, credential


class ObjectStorage:
    def __init__(self, client=None):
        self.client = client

    def _client(self):
        if self.client is not None:
            return self.client
        if os.getenv("ALLOW_EXTERNAL_REQUESTS") != "true":
            raise IntegrationBlocked("Storage uploads require explicit account and data-sharing authorization")
        account = credential("R2_ACCOUNT_ID")
        if not account.isalnum():
            raise ValueError("Invalid R2 account identifier")
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise IntegrationBlocked("Install requirements-storage.txt before connecting object storage") from None
        return boto3.client("s3", region_name="auto", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                            aws_access_key_id=credential("R2_ACCESS_KEY_ID"),
                            aws_secret_access_key=credential("R2_SECRET_ACCESS_KEY"),
                            config=Config(signature_version="s3v4", retries={"total_max_attempts":1}))

    def upload_verified(self, path, expected_sha256, bucket, expires_seconds=604800):
        if not 300 <= expires_seconds <= 604800:
            raise ValueError("Read URL lifetime must be 5 minutes–7 days")
        path=Path(path)
        if not path.is_file() or path.suffix != ".mp4":
            raise ValueError("Only finished MP4 artifacts may be uploaded")
        with path.open("rb") as source:
            actual=hashlib.file_digest(source,"sha256").hexdigest()
        if actual != expected_sha256:
            raise ValueError("Artifact changed since approval")
        key=f"approved/{actual}.mp4"
        client=self._client()
        with path.open("rb") as body:
            client.put_object(Bucket=bucket,Key=key,Body=body,ContentType="video/mp4",Metadata={"sha256":actual})
        head=client.head_object(Bucket=bucket,Key=key)
        if head.get("Metadata",{}).get("sha256") != actual or head.get("ContentLength") != path.stat().st_size:
            raise IntegrationBlocked("Storage verification failed; do not schedule the artifact")
        url=client.generate_presigned_url("get_object",Params={"Bucket":bucket,"Key":key},ExpiresIn=expires_seconds)
        return {"sha256":actual,"key":key,"url":url,"expires_in":expires_seconds,"expires_at":time.time()+expires_seconds,"storage_verified":True,"size":path.stat().st_size}
