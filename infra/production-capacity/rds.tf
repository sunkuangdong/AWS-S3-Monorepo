resource "aws_db_subnet_group" "this" {
  name_prefix = "${local.resource_prefix}-"
  description = "Private subnets for the isolated capacity database"
  subnet_ids  = aws_subnet.private[*].id
}

resource "aws_db_instance" "this" {
  identifier_prefix = "${local.resource_prefix}-"

  engine         = "postgres"
  engine_version = var.database_engine_version
  instance_class = var.database_instance_class

  db_name  = var.database_name
  username = var.database_username
  port     = 5432

  manage_master_user_password = true

  allocated_storage     = var.database_allocated_storage_gib
  max_allocated_storage = max(var.database_allocated_storage_gib, 100)
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1
  copy_tags_to_snapshot   = true
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : (
    "${local.resource_prefix}-final"
  )

  auto_minor_version_upgrade = true
  apply_immediately          = true
  delete_automated_backups   = true
}
