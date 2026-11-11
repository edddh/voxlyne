"""
Voxlyne - S3 Client
S3-compatible storage for PDF files (MinIO local, AWS S3 production)
"""

import logging
from typing import BinaryIO, Optional
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, BotoCoreError

from app.config import get_settings

logger = logging.getLogger(__name__)


class S3ClientError(Exception):
    """Raised when S3 operations fail."""
    pass


class S3Client:
    """
    S3-compatible storage client.
    Works with both MinIO (local) and AWS S3 (production).
    Switch between them by changing S3_ENDPOINT environment variable.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._bucket_initialized = False

    def _get_client(self):
        """Lazy initialization of boto3 client."""
        if self._client is None:
            try:
                # Create boto3 client
                self._client = boto3.client(
                    's3',
                    endpoint_url=self.settings.s3_endpoint,
                    aws_access_key_id=self.settings.s3_access_key,
                    aws_secret_access_key=self.settings.s3_secret_key,
                    region_name=self.settings.s3_region,
                    config=Config(signature_version='s3v4')
                )
                logger.info(
                    f"S3 client initialized: {self.settings.s3_endpoint}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
                raise S3ClientError(f"S3 client initialization failed: {e}") from e

        return self._client

    def ensure_bucket_exists(self) -> None:
        """
        Create bucket if it doesn't exist (idempotent).
        Called automatically before first upload.
        """
        if self._bucket_initialized:
            return

        client = self._get_client()

        try:
            # Check if bucket exists
            client.head_bucket(Bucket=self.settings.s3_bucket)
            logger.debug(f"Bucket {self.settings.s3_bucket} already exists")
            self._bucket_initialized = True

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')

            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    client.create_bucket(
                        Bucket=self.settings.s3_bucket,
                        # ACL='private'  # Not all S3-compatible stores support ACL
                    )
                    logger.info(f"Created bucket: {self.settings.s3_bucket}")
                    self._bucket_initialized = True

                except ClientError as create_error:
                    logger.error(
                        f"Failed to create bucket {self.settings.s3_bucket}: {create_error}"
                    )
                    raise S3ClientError(
                        f"Failed to create bucket: {create_error}"
                    ) from create_error

            elif error_code == '403':
                # Bucket exists but no permission
                raise S3ClientError(
                    f"No permission to access bucket {self.settings.s3_bucket}"
                )
            else:
                raise S3ClientError(f"Bucket check failed: {e}") from e

    def upload_pdf(
        self,
        file_content: bytes,
        call_id: UUID,
        project_slug: str = "default"
    ) -> str:
        """
        Upload PDF file to S3/MinIO.

        Args:
            file_content: PDF file bytes
            call_id: UUID of the call
            project_slug: Project slug for organizing files

        Returns:
            S3 object key (path)

        Raises:
            S3ClientError: If upload fails
        """
        self.ensure_bucket_exists()

        # Generate S3 key: pdfs/{project_slug}/{call_id}.pdf
        key = f"pdfs/{project_slug}/{call_id}.pdf"

        client = self._get_client()

        try:
            client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=file_content,
                ContentType='application/pdf',
                # Metadata for debugging
                Metadata={
                    'call_id': str(call_id),
                    'project': project_slug
                }
            )

            logger.info(f"Uploaded PDF: s3://{self.settings.s3_bucket}/{key}")
            return key

        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to upload PDF for call {call_id}: {e}")
            raise S3ClientError(f"Upload failed: {e}") from e

    def download_pdf(self, key: str) -> bytes:
        """
        Download PDF from S3/MinIO.

        Args:
            key: S3 object key

        Returns:
            PDF file bytes

        Raises:
            S3ClientError: If download fails or file not found
        """
        client = self._get_client()

        try:
            response = client.get_object(
                Bucket=self.settings.s3_bucket,
                Key=key
            )

            pdf_bytes = response['Body'].read()
            logger.debug(f"Downloaded PDF: {key} ({len(pdf_bytes)} bytes)")
            return pdf_bytes

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')

            if error_code == 'NoSuchKey':
                raise S3ClientError(f"PDF not found: {key}")
            else:
                logger.error(f"Failed to download PDF {key}: {e}")
                raise S3ClientError(f"Download failed: {e}") from e

        except BotoCoreError as e:
            logger.error(f"Failed to download PDF {key}: {e}")
            raise S3ClientError(f"Download failed: {e}") from e

    def delete_pdf(self, key: str) -> None:
        """
        Delete PDF from S3/MinIO.
        Used for GDPR hard delete.

        Args:
            key: S3 object key

        Raises:
            S3ClientError: If deletion fails (404 is ignored - idempotent)
        """
        if not key:
            logger.warning("Attempted to delete PDF with empty key")
            return

        client = self._get_client()

        try:
            client.delete_object(
                Bucket=self.settings.s3_bucket,
                Key=key
            )

            logger.info(f"Deleted PDF: {key}")

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')

            if error_code == 'NoSuchKey':
                # File doesn't exist, that's OK (idempotent delete)
                logger.debug(f"PDF already deleted: {key}")
            else:
                logger.error(f"Failed to delete PDF {key}: {e}")
                raise S3ClientError(f"Delete failed: {e}") from e

        except BotoCoreError as e:
            logger.error(f"Failed to delete PDF {key}: {e}")
            raise S3ClientError(f"Delete failed: {e}") from e

    def get_presigned_url(
        self,
        key: str,
        expiration_seconds: int = 3600
    ) -> str:
        """
        Generate presigned URL for temporary PDF download.

        Args:
            key: S3 object key
            expiration_seconds: URL validity duration (default: 1 hour)

        Returns:
            Presigned URL string

        Raises:
            S3ClientError: If URL generation fails
        """
        client = self._get_client()

        try:
            url = client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.settings.s3_bucket,
                    'Key': key
                },
                ExpiresIn=expiration_seconds
            )

            logger.debug(f"Generated presigned URL for {key}")
            return url

        except ClientError as e:
            logger.error(f"Failed to generate presigned URL for {key}: {e}")
            raise S3ClientError(f"Presigned URL generation failed: {e}") from e

    def health_check(self) -> bool:
        """
        Check if S3/MinIO is accessible.
        Used by health check endpoint.

        Returns:
            True if accessible, False otherwise
        """
        try:
            client = self._get_client()
            # List buckets to verify connection
            client.list_buckets()
            return True

        except Exception as e:
            logger.error(f"S3 health check failed: {e}")
            return False


# Singleton instance
_s3_client: Optional[S3Client] = None


def get_s3_client() -> S3Client:
    """
    Get singleton S3 client instance.

    Returns:
        S3Client instance
    """
    global _s3_client

    if _s3_client is None:
        _s3_client = S3Client()

    return _s3_client
