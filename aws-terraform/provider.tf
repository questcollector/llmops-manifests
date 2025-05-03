terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5.1"
    }
  }
  backend "s3" {
    bucket = "llmops-tfstate-rjh22jz2zk"
    key    = "terraform"
    region = "us-east-1"
    use_lockfile = true
    profile = "mspmanager"
  }
}

# Configure the AWS Provider
provider "aws" {
  region = var.region
  profile = "mspmanager"
}
