terraform {
  required_version = "1.17.1"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }

  # The bucket comes from infra/bootstrap. The lock is S3's own: Terraform
  # writes <key>.tflock next to the state with a conditional put, so a second
  # plan or apply finds it and stops. No DynamoDB table.
  backend "s3" {
    bucket       = "rateio-tfstate-k7m2q9"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
