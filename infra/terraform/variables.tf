variable "aws_region" {
  description = "AWS region to deploy SENTINEL resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (e.g. prod, staging)"
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "EC2 instance type for the SENTINEL worker"
  type        = string
  default     = "t3.small"
}

variable "ecr_repo_name" {
  description = "Name of the ECR repository for the SENTINEL Docker image"
  type        = string
  default     = "sentinel"
}
