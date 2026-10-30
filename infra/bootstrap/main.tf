# The bucket that holds infra/prod's remote state, and nothing else.
#
# This configuration keeps its own state locally (infra/bootstrap/terraform.tfstate,
# gitignored): the bucket cannot store the state of the code that creates it.
# Losing that local file loses nothing that matters; the bucket can be brought
# back under management with `terraform import`.

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project = "rateio"
    }
  }
}

resource "aws_s3_bucket" "state" {
  # Global namespace with a fixed random suffix. The account-regional namespace
  # would put the account id in the name, and the name is committed in the
  # backend block of infra/prod.
  bucket = "rateio-tfstate-k7m2q9"

  # Destroying this bucket would orphan every resource in infra/prod.
  lifecycle {
    prevent_destroy = true
  }
}

# Every write keeps the previous state as an older version: a broken apply can
# be rolled back by restoring it.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# The state holds secrets (the database password). SSE-S3 is already the S3
# default; declaring it makes it visible here and lets a plan catch drift.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ACLs off: access is decided by IAM alone.
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}
