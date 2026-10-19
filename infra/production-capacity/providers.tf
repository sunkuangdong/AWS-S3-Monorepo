provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  resource_prefix = substr(
    "${var.project_name}-${var.environment_name}",
    0,
    24,
  )
  availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    2,
  )
  common_tags = merge(
    var.extra_tags,
    {
      Project     = var.project_name
      Environment = var.environment_name
      ManagedBy   = "terraform"
      Purpose     = "isolated-production-capacity-evaluation"
    },
  )
}
