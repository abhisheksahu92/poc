import boto3
from io import BytesIO
from app.config import config

# S3 client
s3_client = boto3.client(
    "s3",
    region_name=config.S3_REGION,
    aws_access_key_id=config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
)

def fetch_png_from_s3(key: str) -> BytesIO:
    """Fetch PNG file from S3 and return as BytesIO buffer."""
    s3_obj = s3_client.get_object(Bucket=config.S3_BUCKET, Key=key)
    return BytesIO(s3_obj["Body"].read())
