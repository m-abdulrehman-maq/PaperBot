# """PDF storage on DigitalOcean Spaces (S3-compatible). Optional.

# If Spaces is not configured, uploads raise a clear error so the admin knows to
# set it up. Uploaded objects are made public-read so WhatsApp can fetch them by
# link.
# """
# import uuid

# import config

# try:
#     import boto3
#     from botocore.client import Config as BotoConfig
#     _HAS_BOTO = True
# except Exception:  # boto3 not installed
#     _HAS_BOTO = False


# def is_configured():
#     return bool(_HAS_BOTO and config.SPACES_KEY and config.SPACES_SECRET
#                 and config.SPACES_BUCKET)


# def _client():
#     return boto3.client(
#         "s3",
#         region_name=config.SPACES_REGION,
#         endpoint_url=config.SPACES_ENDPOINT,
#         aws_access_key_id=config.SPACES_KEY,
#         aws_secret_access_key=config.SPACES_SECRET,
#         # config=BotoConfig(signature_version="s3v4"),
#         config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"})
#     )


# def upload_pdf(data, filename):
#     """Upload bytes and return (public_url, key)."""
#     if not is_configured():
#         raise RuntimeError(
#             "Object storage is not configured. Set SPACES_KEY, SPACES_SECRET "
#             "and SPACES_BUCKET to enable PDF uploads.")
#     safe = "".join(c for c in (filename or "paper.pdf") if c.isalnum() or c in "._-")
#     key = f"papers/{uuid.uuid4().hex}_{safe or 'paper.pdf'}"
#     client = _client()
#     client.put_object(
#         Bucket=config.SPACES_BUCKET,
#         Key=key,
#         Body=data,
#         ACL="public-read",
#         ContentType="application/pdf",
#     )
#     # url = f"{config.SPACES_ENDPOINT}/{config.SPACES_BUCKET}/{key}"
#     # return url, key
#     def upload_pdf(data, filename):
#      if not is_configured():
#         raise RuntimeError(
#             "Object storage is not configured. Set SPACES_KEY, SPACES_SECRET "
#             "and SPACES_BUCKET to enable PDF uploads.")
#      safe = "".join(c for c in (filename or "paper.pdf") if c.isalnum() or c in "._-")
#      key = f"papers/{uuid.uuid4().hex}_{safe or 'paper.pdf'}"
#      client = _client()
#      client.put_object(
#         Bucket=config.SPACES_BUCKET,
#         Key=key,
#         Body=data,
#         ContentType="application/pdf",
#      )
#      # Build the public object URL (different from the S3 API endpoint)
#      project_domain = config.SPACES_ENDPOINT.split("//")[1].split(".storage.supabase.co")[0]
#      url = f"https://{project_domain}.supabase.co/storage/v1/object/public/{config.SPACES_BUCKET}/{key}"
#      return url, key

"""PDF storage on Supabase Storage (S3-compatible).

If Spaces is not configured, uploads raise a clear error so the admin knows to
set it up. Uploaded objects are made public-read so WhatsApp can fetch them by
link.
"""
import uuid

import config

try:
    import boto3
    from botocore.client import Config as BotoConfig
    _HAS_BOTO = True
except Exception:  # boto3 not installed
    _HAS_BOTO = False


def is_configured():
    return bool(_HAS_BOTO and config.SPACES_KEY and config.SPACES_SECRET
                and config.SPACES_BUCKET)


def _client():
    return boto3.client(
        "s3",
        region_name=config.SPACES_REGION,
        endpoint_url=config.SPACES_ENDPOINT,
        aws_access_key_id=config.SPACES_KEY,
        aws_secret_access_key=config.SPACES_SECRET,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def upload_pdf(data, filename):
    """Upload bytes and return (public_url, key)."""
    if not is_configured():
        raise RuntimeError(
            "Object storage is not configured. Set SPACES_KEY, SPACES_SECRET "
            "and SPACES_BUCKET to enable PDF uploads.")
    safe = "".join(c for c in (filename or "paper.pdf") if c.isalnum() or c in "._-")
    key = f"papers/{uuid.uuid4().hex}_{safe or 'paper.pdf'}"
    client = _client()
    client.put_object(
        Bucket=config.SPACES_BUCKET,
        Key=key,
        Body=data,
        ContentType="application/pdf",
    )
    # Build the public object URL (different from the S3 API endpoint)
    project_domain = config.SPACES_ENDPOINT.split("//")[1].split(".storage.supabase.co")[0]
    url = f"https://{project_domain}.supabase.co/storage/v1/object/public/{config.SPACES_BUCKET}/{key}"
    return url, key