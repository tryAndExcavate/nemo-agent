import io
import logging
from minio import Minio
from app.config import settings

logger = logging.getLogger(__name__)


class MinioService:
    """MinIO 对象存储服务（延迟连接，启动时不阻塞）"""

    def __init__(self):
        self._client: Minio | None = None
        self.bucket_name = settings.minio_bucket_name
        self._initialized = False

    @property
    def client(self) -> Minio:
        if self._client is None:
            import urllib3
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                http_client=urllib3.PoolManager(
                    timeout=5,
                    retries=urllib3.Retry(total=1, connect=1, read=1, redirect=0),
                ),
            )
            self._ensure_bucket()
            logger.info(f"MinIO connected: endpoint={settings.minio_endpoint}, bucket={self.bucket_name}")
        return self._client

    def _ensure_bucket(self):
        try:
            if not self._client.bucket_exists(self.bucket_name):
                self._client.make_bucket(self.bucket_name)
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"],
                        }
                    ],
                }
                self._client.set_bucket_policy(self.bucket_name, str(policy))
        except Exception as e:
            logger.warning(f"MinIO bucket init failed: {e}")

    def upload_file(self, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return self.get_public_url(object_name)

    def download_file(self, object_name: str) -> bytes:
        response = self.client.get_object(self.bucket_name, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_public_url(self, object_name: str) -> str:
        protocol = "https" if settings.minio_secure else "http"
        return f"{protocol}://{settings.minio_endpoint}/{self.bucket_name}/{object_name}"

    def delete_file(self, object_name: str):
        try:
            self.client.remove_object(self.bucket_name, object_name)
        except Exception as e:
            logger.warning(f"MinIO delete failed: {e}")


minio_service = MinioService()


def generate_object_name(file_id: str, file_type: str) -> str:
    return f"files/{file_id}/{file_id}.{file_type}"
