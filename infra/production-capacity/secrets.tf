locals {
  application_secret_names = toset([
    "capacity_metrics_authorization",
    "database_url",
    "langfuse_public_key",
    "langfuse_secret_key",
    "openai_api_key",
  ])
}

resource "aws_secretsmanager_secret" "application" {
  for_each = local.application_secret_names

  name_prefix             = "${local.resource_prefix}/${each.value}-"
  description             = "${each.value} for the isolated capacity environment"
  recovery_window_in_days = 7

  tags = {
    SecretPurpose = each.value
  }
}

# Secret versions are deliberately not managed by Terraform. Values must be
# inserted after the first apply so they never enter source code, tfvars, plan
# files, or Terraform state.
