terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── Data Sources ──────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── ECR Repository ────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "sentinel" {
  name                 = var.ecr_repo_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = var.ecr_repo_name
    Environment = var.environment
  }
}

resource "aws_ecr_lifecycle_policy" "sentinel" {
  repository = aws_ecr_repository.sentinel.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ── DynamoDB Tables ───────────────────────────────────────────────────────────

resource "aws_dynamodb_table" "sentinel_ideas" {
  name           = "sentinel_ideas"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "idea_id"

  attribute {
    name = "idea_id"
    type = "S"
  }

  attribute {
    name = "pm_user_id"
    type = "S"
  }

  attribute {
    name = "is_active"
    type = "S"
  }

  global_secondary_index {
    name            = "pm_user_id-index"
    hash_key        = "pm_user_id"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "is_active-index"
    hash_key        = "is_active"
    projection_type = "ALL"
  }

  tags = {
    Name        = "sentinel_ideas"
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "sentinel_articles" {
  name           = "sentinel_articles"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "article_id"

  attribute {
    name = "article_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name        = "sentinel_articles"
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "sentinel_alerts" {
  name           = "sentinel_alerts"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "alert_id"

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "idea_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "idea_id-created_at-index"
    hash_key        = "idea_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = {
    Name        = "sentinel_alerts"
    Environment = var.environment
  }
}

# ── IAM Role & Policy for EC2 ─────────────────────────────────────────────────

resource "aws_iam_role" "sentinel_ec2_role" {
  name = "sentinel-ec2-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "sentinel-ec2-role"
    Environment = var.environment
  }
}

resource "aws_iam_policy" "sentinel_policy" {
  name        = "sentinel-policy-${var.environment}"
  description = "Policy granting SENTINEL worker access to DynamoDB, Secrets Manager, CloudWatch, and ECR"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBFullAccessSentinelTables"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:DescribeTable",
        ]
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/sentinel_*",
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/sentinel_*/index/*",
        ]
      },
      {
        Sid    = "SecretsManagerReadSentinel"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:sentinel/*",
        ]
      },
      {
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/sentinel/*",
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/sentinel/*:*",
        ]
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "sentinel-policy"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "sentinel_policy_attachment" {
  role       = aws_iam_role.sentinel_ec2_role.name
  policy_arn = aws_iam_policy.sentinel_policy.arn
}

resource "aws_iam_instance_profile" "sentinel_profile" {
  name = "sentinel-instance-profile-${var.environment}"
  role = aws_iam_role.sentinel_ec2_role.name

  tags = {
    Name        = "sentinel-instance-profile"
    Environment = var.environment
  }
}

# ── Security Group ────────────────────────────────────────────────────────────

resource "aws_security_group" "sentinel" {
  name        = "sentinel-sg-${var.environment}"
  description = "Security group for SENTINEL EC2 worker"

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # Restrict to your IP in production
  }

  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "sentinel-sg"
    Environment = var.environment
  }
}

# ── EC2 Instance ──────────────────────────────────────────────────────────────

resource "aws_instance" "sentinel" {
  ami                  = data.aws_ami.amazon_linux_2023.id
  instance_type        = var.instance_type
  iam_instance_profile = aws_iam_instance_profile.sentinel_profile.name
  security_groups      = [aws_security_group.sentinel.name]

  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -e
    # Install Docker
    dnf install -y docker
    systemctl start docker
    systemctl enable docker
    usermod -a -G docker ec2-user

    # Install AWS CLI v2 (already present on AL2023)
    # Login to ECR and pull the latest image will be done by deploy.sh
    echo "SENTINEL EC2 instance initialized."
  EOF
  )

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name        = "sentinel-worker-${var.environment}"
    Environment = var.environment
  }
}

# ── Secrets Manager ───────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "sentinel/anthropic_api_key"
  description             = "Anthropic API key for SENTINEL"
  recovery_window_in_days = 7

  tags = {
    Name        = "sentinel/anthropic_api_key"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "{}"  # Fill manually after deployment
}

resource "aws_secretsmanager_secret" "benzinga_api_key" {
  name                    = "sentinel/benzinga_api_key"
  description             = "Benzinga API key for SENTINEL"
  recovery_window_in_days = 7

  tags = {
    Name        = "sentinel/benzinga_api_key"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "benzinga_api_key" {
  secret_id     = aws_secretsmanager_secret.benzinga_api_key.id
  secret_string = "{}"
}

resource "aws_secretsmanager_secret" "slack_bot_token" {
  name                    = "sentinel/slack_bot_token"
  description             = "Slack Bot Token for SENTINEL"
  recovery_window_in_days = 7

  tags = {
    Name        = "sentinel/slack_bot_token"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "slack_bot_token" {
  secret_id     = aws_secretsmanager_secret.slack_bot_token.id
  secret_string = "{}"
}

resource "aws_secretsmanager_secret" "slack_app_token" {
  name                    = "sentinel/slack_app_token"
  description             = "Slack App Token for SENTINEL"
  recovery_window_in_days = 7

  tags = {
    Name        = "sentinel/slack_app_token"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "slack_app_token" {
  secret_id     = aws_secretsmanager_secret.slack_app_token.id
  secret_string = "{}"
}

resource "aws_secretsmanager_secret" "slack_signing_secret" {
  name                    = "sentinel/slack_signing_secret"
  description             = "Slack Signing Secret for SENTINEL"
  recovery_window_in_days = 7

  tags = {
    Name        = "sentinel/slack_signing_secret"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "slack_signing_secret" {
  secret_id     = aws_secretsmanager_secret.slack_signing_secret.id
  secret_string = "{}"
}

# ── CloudWatch ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "sentinel_worker" {
  name              = "/sentinel/worker"
  retention_in_days = 30

  tags = {
    Name        = "sentinel-worker-logs"
    Environment = var.environment
  }
}

# SNS Topic for CloudWatch Alarms
resource "aws_sns_topic" "sentinel_alerts" {
  name = "sentinel-alerts-${var.environment}"

  tags = {
    Name        = "sentinel-alerts"
    Environment = var.environment
  }
}

# Alarm: Worker Heartbeat — detect if the worker stops logging
resource "aws_cloudwatch_metric_alarm" "worker_heartbeat" {
  alarm_name          = "sentinel-worker-heartbeat-${var.environment}"
  alarm_description   = "Triggers if SENTINEL worker stops emitting heartbeat logs"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "IncomingLogEvents"
  namespace           = "AWS/Logs"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"

  dimensions = {
    LogGroupName = aws_cloudwatch_log_group.sentinel_worker.name
  }

  alarm_actions = [aws_sns_topic.sentinel_alerts.arn]
  ok_actions    = [aws_sns_topic.sentinel_alerts.arn]

  tags = {
    Name        = "sentinel-worker-heartbeat"
    Environment = var.environment
  }
}

# Metric filter for exceptions
resource "aws_cloudwatch_log_metric_filter" "exception_filter" {
  name           = "sentinel-exceptions"
  pattern        = "{ $.level = \"error\" }"
  log_group_name = aws_cloudwatch_log_group.sentinel_worker.name

  metric_transformation {
    name      = "ExceptionCount"
    namespace = "SENTINEL/Worker"
    value     = "1"
  }
}

# Alarm: Exception Rate
resource "aws_cloudwatch_metric_alarm" "exception_rate" {
  alarm_name          = "sentinel-exception-rate-${var.environment}"
  alarm_description   = "Triggers if SENTINEL worker exception rate is too high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ExceptionCount"
  namespace           = "SENTINEL/Worker"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.sentinel_alerts.arn]

  tags = {
    Name        = "sentinel-exception-rate"
    Environment = var.environment
  }
}

# Metric filter for Anthropic errors
resource "aws_cloudwatch_log_metric_filter" "anthropic_error_filter" {
  name           = "sentinel-anthropic-errors"
  pattern        = "{ $.event = \"sentinel.relevance.error\" || $.event = \"sentinel.impact.failed\" }"
  log_group_name = aws_cloudwatch_log_group.sentinel_worker.name

  metric_transformation {
    name      = "AnthropicErrorCount"
    namespace = "SENTINEL/Worker"
    value     = "1"
  }
}

# Alarm: Anthropic Error Rate
resource "aws_cloudwatch_metric_alarm" "anthropic_error_rate" {
  alarm_name          = "sentinel-anthropic-error-rate-${var.environment}"
  alarm_description   = "Triggers if Anthropic API errors exceed threshold"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "AnthropicErrorCount"
  namespace           = "SENTINEL/Worker"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.sentinel_alerts.arn]

  tags = {
    Name        = "sentinel-anthropic-error-rate"
    Environment = var.environment
  }
}
