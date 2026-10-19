output "api_base_url" {
  description = "HTTPS endpoint for free preflight and the reviewed capacity runner."
  value       = "https://${var.api_domain_name}"
}

output "metrics_url" {
  description = "Protected resource-metrics endpoint."
  value       = "https://${var.api_domain_name}/internal/capacity-metrics"
}

output "ecr_repository_url" {
  description = "Push the reviewed linux/amd64 API image here."
  value       = aws_ecr_repository.api.repository_url
}

output "image_uri" {
  description = "Immutable image URI captured by the task definitions."
  value       = local.api_image
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "migration_task_definition_arn" {
  description = "Run exactly once after populating secrets and pushing the image."
  value       = aws_ecs_task_definition.migration.arn
}

output "private_subnet_ids" {
  description = "Network configuration for the one-off migration task."
  value       = aws_subnet.private[*].id
}

output "ecs_security_group_id" {
  description = "Security group for the one-off migration task."
  value       = aws_security_group.ecs.id
}

output "database_endpoint" {
  description = "Private host and port used to construct the application DATABASE_URL secret."
  value       = aws_db_instance.this.endpoint
}

output "database_master_secret_arn" {
  description = "RDS-managed master credential secret; its value never enters Terraform state."
  value       = try(aws_db_instance.this.master_user_secret[0].secret_arn, null)
}

output "application_secret_arns" {
  description = "Populate each secret after the first apply; never put values in tfvars."
  value = {
    for name, secret in aws_secretsmanager_secret.application : name => secret.arn
  }
}

output "deployment_identity" {
  description = "AWS identity that applied this stack."
  value = {
    account_id = data.aws_caller_identity.current.account_id
    arn        = data.aws_caller_identity.current.arn
  }
}
