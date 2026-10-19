# Isolated production-capacity infrastructure

This root module provisions an isolated, deployment-specific environment for
the real-dependency capacity protocol. It does **not** turn the existing local
Stub benchmark into a production-capacity claim.

## Safety properties

- The default ECS desired count is `0`, so the first apply cannot invoke the
  application or OpenAI.
- Terraform creates only empty application secret containers. Secret values
  are inserted manually and never belong in source code, tfvars, plan files, or
  Terraform state.
- The existing capacity S3 bucket is referenced by name and is not managed or
  deleted by this module.
- RDS is private, encrypted, and reachable only from the ECS task security
  group.
- ECS tasks are private. A restricted HTTPS ALB is the only application entry
  point.
- The API container does not run Alembic. A separate one-off migration task
  prevents two service replicas from racing a schema migration.
- The ECR repository is immutable and refuses deletion while it contains
  images.

This stack creates billable resources including a NAT gateway, ALB, Fargate,
RDS, Route53 records, CloudWatch logs, Secrets Manager secrets, and ECR storage.
AWS Budgets is not a hard spending stop. Review the plan and destroy the
temporary stack promptly after evidence is frozen.

The draft topology intentionally uses one NAT gateway and Single-AZ RDS to
bound an isolated capacity experiment. It is not a high-availability or
disaster-recovery test, and its results must not be presented as availability
or production SLO evidence.

## Required manual inputs

1. A Terraform deployment identity. Do not grant infrastructure permissions to
   the application IAM user used for S3 validation.
2. Terraform `1.16.x` and AWS provider `6.69.x`.
3. An existing Route53 public hosted zone and a dedicated hostname.
4. The existing isolated capacity S3 bucket.
5. A dedicated OpenAI project key and Langfuse project or environment.
6. The current operator/load-generator public IPv4 address as a `/32` CIDR.

The deployment identity must be able to manage VPC, EC2 networking, ALB, ACM,
Route53, ECS, ECR, IAM roles, RDS, Secrets Manager, and CloudWatch Logs. Use
short-lived credentials where possible; never commit provider credentials.

## 1. Prepare and validate configuration

From the repository root:

```bash
cd infra/production-capacity
cp terraform.tfvars.example terraform.tfvars
```

Edit only non-secret deployment inputs in `terraform.tfvars`. Keep
`service_desired_count = 0` for the first apply.

```bash
terraform fmt -recursive
terraform init
terraform validate
terraform plan -out=bootstrap.tfplan
terraform show bootstrap.tfplan
```

Manually verify before apply:

- the AWS account and Region are the intended isolated target;
- no existing user VPC, database, bucket, or service will be modified;
- RDS is not publicly accessible;
- ALB ingress contains only reviewed `/32` addresses;
- ECS desired count is `0`;
- the S3 bucket name is the dedicated capacity bucket;
- no secret values appear in the plan.

Apply only the reviewed saved plan:

```bash
terraform apply bootstrap.tfplan
```

The first apply creates billable infrastructure but does not start API tasks or
make OpenAI calls.

## 2. Build and push the reviewed image

Use the exact `image_tag` recorded in `terraform.tfvars`. From this directory:

```bash
export AWS_REGION='us-east-1'
export ECR_REPOSITORY_URL="$(terraform output -raw ecr_repository_url)"
export IMAGE_TAG='e5ceaaf'

aws ecr get-login-password --region "$AWS_REGION" |
  docker login \
    --username AWS \
    --password-stdin "${ECR_REPOSITORY_URL%%/*}"

docker buildx build \
  --platform linux/amd64 \
  --file ../../apps/api/Dockerfile \
  --tag "$ECR_REPOSITORY_URL:$IMAGE_TAG" \
  --push \
  ../..
```

Do not reuse a mutable `latest` tag.

## 3. Populate Secrets Manager

Read the empty secret ARNs without exposing values:

```bash
terraform output -json application_secret_arns
terraform output -raw database_endpoint
terraform output -raw database_master_secret_arn
```

Use the AWS console or an approved secret-management workflow to populate:

| Secret | Required value |
| --- | --- |
| `openai_api_key` | Dedicated OpenAI project/service-account key |
| `langfuse_public_key` | Dedicated Langfuse project public key |
| `langfuse_secret_key` | Dedicated Langfuse project secret key |
| `capacity_metrics_authorization` | Complete `Bearer <random-secret>` header |
| `database_url` | URL-encoded PostgreSQL SQLAlchemy URL using the private RDS endpoint |

Retrieve the RDS-managed master password from the ARN printed by
`database_master_secret_arn`. Construct the application secret in this form,
URL-encoding the username and password:

```text
postgresql+psycopg://USER:PASSWORD@PRIVATE_RDS_ENDPOINT/ai_image_capacity?sslmode=require&application_name=production_capacity
```

Never paste any of these values into chat, Git, Terraform variables, plan
files, command history, or evaluation artifacts.

## 4. Run exactly one migration task

In the ECS console:

1. Open the cluster printed by `terraform output -raw ecs_cluster_name`.
2. Choose **Run new task**, launch type **Fargate**.
3. Select the task definition printed by
   `terraform output -raw migration_task_definition_arn`.
4. Select both private subnets from `terraform output -json private_subnet_ids`.
5. Select the ECS security group from
   `terraform output -raw ecs_security_group_id`.
6. Disable public IP assignment and run one task.
7. Confirm exit code `0` and review the migration CloudWatch log stream.

Do not start the API service until the migration succeeds.

## 5. Start one task and run the free remote preflight

Set `service_desired_count = 1`, then:

```bash
terraform plan -out=start-one.tfplan
terraform show start-one.tfplan
terraform apply start-one.tfplan
```

Wait for the target to become healthy and verify:

```bash
terraform output -raw api_base_url
terraform output -raw metrics_url
```

Run `evals.run_production_capacity --validate-only` against those HTTPS URLs.
The expected result includes `paid_model_calls: 0` and every preflight
capability set to `true`.

## 6. Review two-task observability before capacity testing

The current `/internal/capacity-metrics` endpoint reports the Fargate task that
handled that request plus global PostgreSQL connections. Behind two replicas,
it does not prove that every task was sampled. Therefore:

- one-task remote preflight and Pilot evidence are valid only for the one-task
  topology;
- do not claim two-task CPU or memory saturation from this endpoint alone;
- add service-level or per-task metrics coverage before setting
  `service_desired_count = 2` for a final multi-replica capacity claim.

This limitation is intentional and fail-safe. It prevents a load-balanced
deployment from producing an unsupported aggregate resource claim.

## 7. Teardown

First set `service_desired_count = 0` and apply. Export all approved evidence,
then inspect the destroy plan:

```bash
terraform plan -destroy -out=destroy.tfplan
terraform show destroy.tfplan
```

The ECR repository has `force_delete = false`; delete its test images only after
confirming they are no longer required. Then apply the reviewed destroy plan:

```bash
terraform apply destroy.tfplan
```

Secrets are scheduled for deletion with a seven-day recovery window. The
existing S3 bucket and its reference object remain outside this Terraform
stack.
