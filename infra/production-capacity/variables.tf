variable "aws_region" {
  description = "AWS Region for every regional capacity resource."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short resource-name prefix."
  type        = string
  default     = "ai-image"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.project_name))
    error_message = "project_name must be 2-16 lowercase letters, digits, or hyphens."
  }
}

variable "environment_name" {
  description = "Isolated environment label."
  type        = string
  default     = "capacity"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment_name))
    error_message = "environment_name must be 2-16 lowercase letters, digits, or hyphens."
  }
}

variable "vpc_cidr" {
  description = "CIDR for the isolated VPC."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid CIDR."
  }
}

variable "public_subnet_cidrs" {
  description = "Two public subnet CIDRs for the ALB and NAT gateway."
  type        = list(string)
  default     = ["10.42.0.0/24", "10.42.1.0/24"]

  validation {
    condition = (
      length(var.public_subnet_cidrs) == 2 &&
      alltrue([for cidr in var.public_subnet_cidrs : can(cidrhost(cidr, 0))])
    )
    error_message = "public_subnet_cidrs must contain exactly two valid CIDRs."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private subnet CIDRs for ECS and RDS."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.11.0/24"]

  validation {
    condition = (
      length(var.private_subnet_cidrs) == 2 &&
      alltrue([for cidr in var.private_subnet_cidrs : can(cidrhost(cidr, 0))])
    )
    error_message = "private_subnet_cidrs must contain exactly two valid CIDRs."
  }
}

variable "allowed_ingress_cidrs" {
  description = "Operator/load-generator public CIDRs allowed to reach the ALB."
  type        = list(string)

  validation {
    condition = (
      length(var.allowed_ingress_cidrs) > 0 &&
      alltrue([
        for cidr in var.allowed_ingress_cidrs :
        can(cidrhost(cidr, 0)) && can(regex("^[0-9.]+/[0-9]+$", cidr))
      ]) &&
      !contains(var.allowed_ingress_cidrs, "0.0.0.0/0") &&
      !contains(var.allowed_ingress_cidrs, "::/0")
    )
    error_message = "Provide at least one valid restricted CIDR; public internet CIDRs are forbidden."
  }
}

variable "api_domain_name" {
  description = "Dedicated API hostname in the supplied Route53 public zone."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]+[a-z0-9]$", var.api_domain_name))
    error_message = "api_domain_name must be a valid lowercase DNS hostname."
  }
}

variable "route53_zone_id" {
  description = "Existing Route53 public hosted-zone ID for api_domain_name."
  type        = string

  validation {
    condition     = length(trimspace(var.route53_zone_id)) > 0
    error_message = "route53_zone_id is required."
  }
}

variable "s3_bucket_name" {
  description = "Existing isolated capacity-test S3 bucket; Terraform will not own it."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.s3_bucket_name))
    error_message = "s3_bucket_name must be a valid existing bucket name."
  }
}

variable "image_tag" {
  description = "Immutable ECR image tag, normally the reviewed Git commit SHA."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid non-empty ECR tag."
  }
}

variable "vision_model" {
  description = "Reviewed OpenAI vision model name."
  type        = string

  validation {
    condition     = length(trimspace(var.vision_model)) > 0
    error_message = "vision_model is required."
  }
}

variable "image_generation_model" {
  description = "Reviewed OpenAI image-generation model name."
  type        = string

  validation {
    condition     = length(trimspace(var.image_generation_model)) > 0
    error_message = "image_generation_model is required."
  }
}

variable "frontend_origin" {
  description = "Exact allowed CORS origin; use a non-user-facing isolated origin."
  type        = string

  validation {
    condition     = can(regex("^https://", var.frontend_origin))
    error_message = "frontend_origin must use HTTPS."
  }
}

variable "langfuse_base_url" {
  description = "Langfuse regional base URL."
  type        = string
  default     = "https://us.cloud.langfuse.com"

  validation {
    condition     = can(regex("^https://", var.langfuse_base_url))
    error_message = "langfuse_base_url must use HTTPS."
  }
}

variable "langfuse_environment" {
  description = "Dedicated Langfuse environment label."
  type        = string
  default     = "production-capacity-isolated"
}

variable "task_cpu" {
  description = "Fargate task CPU units; protocol v1 expects 2048 (2 vCPU)."
  type        = number
  default     = 2048

  validation {
    condition     = var.task_cpu == 2048
    error_message = "Protocol v1 requires task_cpu=2048; revise the protocol before changing it."
  }
}

variable "task_memory" {
  description = "Fargate task memory in MiB; protocol v1 expects 4096 (4 GiB)."
  type        = number
  default     = 4096

  validation {
    condition     = var.task_memory == 4096
    error_message = "Protocol v1 requires task_memory=4096; revise the protocol before changing it."
  }
}

variable "service_desired_count" {
  description = "API task count. Keep 0 until secrets, image, and migration are ready."
  type        = number
  default     = 0

  validation {
    condition = (
      var.service_desired_count >= 0 &&
      var.service_desired_count <= 2 &&
      floor(var.service_desired_count) == var.service_desired_count
    )
    error_message = "service_desired_count must be 0, 1, or 2."
  }
}

variable "database_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "ai_image_capacity"
}

variable "database_username" {
  description = "RDS master username; the password is managed by RDS in Secrets Manager."
  type        = string
  default     = "aiimagecapacityadmin"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9]{0,62}$", var.database_username))
    error_message = "database_username must start with a letter and contain only letters or digits."
  }
}

variable "database_instance_class" {
  description = "RDS instance class bound to the resulting capacity claim."
  type        = string
  default     = "db.t4g.medium"
}

variable "database_engine_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "17"
}

variable "database_allocated_storage_gib" {
  description = "Initial encrypted gp3 storage in GiB."
  type        = number
  default     = 20

  validation {
    condition     = var.database_allocated_storage_gib >= 20
    error_message = "database_allocated_storage_gib must be at least 20."
  }
}

variable "database_pool_size" {
  description = "SQLAlchemy pool size per API task."
  type        = number
  default     = 20
}

variable "database_max_overflow" {
  description = "SQLAlchemy overflow connections per API task."
  type        = number
  default     = 20
}

variable "database_pool_timeout_seconds" {
  description = "SQLAlchemy pool checkout timeout."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch application log retention."
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Protect ALB and RDS from deletion after evidence is accepted."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip the RDS final snapshot for this synthetic temporary environment."
  type        = bool
  default     = true
}

variable "extra_tags" {
  description = "Additional non-sensitive resource tags."
  type        = map(string)
  default     = {}
}
