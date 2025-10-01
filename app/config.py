import os

class Config:
    S3_BUCKET = os.getenv("S3_BUCKET", "my-poc-bucket")
    S3_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

config = Config()
