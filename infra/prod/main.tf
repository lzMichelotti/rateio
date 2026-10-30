# The single environment: everything the bot runs on.

provider "aws" {
  region = "us-east-1"

  # Every resource carries the tag, so Cost Explorer can filter on it.
  default_tags {
    tags = {
      project = "rateio"
    }
  }
}
