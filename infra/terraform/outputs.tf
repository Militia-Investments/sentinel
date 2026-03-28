output "ec2_public_ip" {
  description = "Public IP address of the SENTINEL EC2 worker instance"
  value       = aws_instance.sentinel.public_ip
}

output "dynamodb_table_arns" {
  description = "ARNs of all SENTINEL DynamoDB tables"
  value = {
    ideas    = aws_dynamodb_table.sentinel_ideas.arn
    articles = aws_dynamodb_table.sentinel_articles.arn
    alerts   = aws_dynamodb_table.sentinel_alerts.arn
  }
}

output "iam_role_arn" {
  description = "ARN of the IAM role attached to the SENTINEL EC2 instance"
  value       = aws_iam_role.sentinel_ec2_role.arn
}

output "ecr_repository_url" {
  description = "URL of the ECR repository for the SENTINEL Docker image"
  value       = aws_ecr_repository.sentinel.repository_url
}
