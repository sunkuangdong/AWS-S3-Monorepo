resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.resource_prefix}/api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/ecs/${local.resource_prefix}/migration"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "this" {
  name = local.resource_prefix

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

locals {
  api_environment = {
    AWS_DEFAULT_REGION            = var.aws_region
    DATABASE_MAX_OVERFLOW         = tostring(var.database_max_overflow)
    DATABASE_POOL_SIZE            = tostring(var.database_pool_size)
    DATABASE_POOL_TIMEOUT_SECONDS = tostring(var.database_pool_timeout_seconds)
    FRONTEND_ORIGIN               = var.frontend_origin
    IMAGE_GENERATION_MODEL        = var.image_generation_model
    LANGFUSE_BASE_URL             = var.langfuse_base_url
    LANGFUSE_ENVIRONMENT          = var.langfuse_environment
    LANGFUSE_TRACING_ENABLED      = "true"
    LOG_LEVEL                     = "INFO"
    MAX_UPLOAD_BYTES              = "10485760"
    MODEL_NAME                    = var.vision_model
    S3_BUCKET                     = var.s3_bucket_name
    S3_PRESIGNED_URL_EXPIRES      = "600"
  }
  api_secrets = {
    CAPACITY_METRICS_AUTHORIZATION = aws_secretsmanager_secret.application["capacity_metrics_authorization"].arn
    DATABASE_URL                   = aws_secretsmanager_secret.application["database_url"].arn
    LANGFUSE_PUBLIC_KEY            = aws_secretsmanager_secret.application["langfuse_public_key"].arn
    LANGFUSE_SECRET_KEY            = aws_secretsmanager_secret.application["langfuse_secret_key"].arn
    OPENAI_API_KEY                 = aws_secretsmanager_secret.application["openai_api_key"].arn
  }
  api_image = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.resource_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.task_cpu)
  memory                   = tostring(var.task_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.api_image
      essential = true
      command = [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
      ]
      portMappings = [
        {
          name          = "http"
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        },
      ]
      environment = [
        for name, value in local.api_environment : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, value_from in local.api_secrets : {
          name      = name
          valueFrom = value_from
        }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health/database', timeout=3)\"",
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      linuxParameters = {
        initProcessEnabled = true
      }
      stopTimeout = 120
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    },
  ])
}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.resource_prefix}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "migration"
      image     = local.api_image
      essential = true
      command   = ["alembic", "upgrade", "head"]
      environment = [
        for name, value in local.api_environment : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, value_from in local.api_secrets : {
          name      = name
          valueFrom = value_from
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.migration.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "migration"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${local.resource_prefix}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.service_desired_count
  launch_type     = "FARGATE"

  platform_version = "LATEST"
  propagate_tags   = "SERVICE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = false
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy_attachment.execution,
    aws_lb_listener.https,
  ]
}
