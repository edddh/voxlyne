"""
Ascolta - Storage Module
S3-compatible storage client (MinIO local, AWS S3 production)
"""

from app.storage.s3_client import S3Client, get_s3_client

__all__ = ["S3Client", "get_s3_client"]
