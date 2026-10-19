mock_provider "aws" {
  override_data {
    target = data.aws_availability_zones.available
    values = {
      names = ["us-east-1a", "us-east-1b"]
    }
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:role/terraform-test"
    }
  }

  override_data {
    target = data.aws_partition.current
    values = {
      partition = "aws"
    }
  }

  override_resource {
    target = aws_acm_certificate.api
    values = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/mock"
      domain_validation_options = [
        {
          domain_name           = "capacity-api.example.com"
          resource_record_name  = "_mock.capacity-api.example.com"
          resource_record_type  = "CNAME"
          resource_record_value = "_validation.example.com"
        },
      ]
    }
  }
}

variables {
  allowed_ingress_cidrs  = ["203.0.113.10/32"]
  api_domain_name        = "capacity-api.example.com"
  route53_zone_id        = "Z0123456789EXAMPLE"
  s3_bucket_name         = "isolated-capacity-example"
  image_tag              = "e5ceaaf"
  vision_model           = "reviewed-vision-model"
  image_generation_model = "reviewed-image-model"
  frontend_origin        = "https://capacity-ui.example.com"
}

run "safe_zero_task_bootstrap" {
  command = plan

  assert {
    condition     = aws_ecs_service.api.desired_count == 0
    error_message = "The bootstrap plan must not start API tasks."
  }

  assert {
    condition     = aws_db_instance.this.publicly_accessible == false
    error_message = "The capacity database must remain private."
  }

  assert {
    condition = (
      aws_ecs_task_definition.api.cpu == "2048" &&
      aws_ecs_task_definition.api.memory == "4096"
    )
    error_message = "Protocol v1 must keep the reviewed 2-vCPU/4-GiB task shape."
  }

  assert {
    condition     = aws_ecr_repository.api.image_tag_mutability == "IMMUTABLE"
    error_message = "Capacity evidence must reference an immutable image tag."
  }
}

run "reject_public_internet_ingress" {
  command = plan

  variables {
    allowed_ingress_cidrs = ["0.0.0.0/0"]
  }

  expect_failures = [var.allowed_ingress_cidrs]
}

run "reject_unreviewed_replica_count" {
  command = plan

  variables {
    service_desired_count = 3
  }

  expect_failures = [var.service_desired_count]
}
