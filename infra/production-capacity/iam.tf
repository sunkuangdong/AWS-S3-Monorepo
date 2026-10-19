resource "aws_iam_role" "execution" {
  name_prefix = "${local.resource_prefix}-execution-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name_prefix = "${local.resource_prefix}-secrets-"
  role        = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadOnlyReviewedApplicationSecrets"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          for secret in aws_secretsmanager_secret.application : secret.arn
        ]
      },
    ]
  })
}

resource "aws_iam_role" "task" {
  name_prefix = "${local.resource_prefix}-task-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "task_s3" {
  name_prefix = "${local.resource_prefix}-s3-"
  role        = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadWriteOnlyCapacityObjectPrefixes"
        Effect = "Allow"
        Action = [
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:s3:::${var.s3_bucket_name}/generations/*",
          "arn:${data.aws_partition.current.partition}:s3:::${var.s3_bucket_name}/uploads/*",
        ]
      },
    ]
  })
}
