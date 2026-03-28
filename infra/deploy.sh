#!/bin/bash
# SENTINEL Deployment Script
# Usage: ./infra/deploy.sh [environment]
# Requires: terraform, aws cli, docker, ssh key configured

set -euo pipefail

ENVIRONMENT="${1:-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/terraform"

echo "==> [1/5] Running Terraform apply (environment: ${ENVIRONMENT})..."
cd "${TERRAFORM_DIR}"
terraform init -upgrade
terraform apply \
  -var "environment=${ENVIRONMENT}" \
  -var "aws_region=${AWS_REGION}" \
  -auto-approve

# Capture outputs
ECR_URL=$(terraform output -raw ecr_repository_url)
EC2_IP=$(terraform output -raw ec2_public_ip)

echo "    ECR URL: ${ECR_URL}"
echo "    EC2 IP:  ${EC2_IP}"

echo "==> [2/5] Building Docker image..."
cd "${REPO_ROOT}"
IMAGE_TAG="${ECR_URL}:latest"
docker build \
  --platform linux/amd64 \
  -f docker/Dockerfile \
  -t "${IMAGE_TAG}" \
  .

echo "==> [3/5] Authenticating to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"

echo "==> [4/5] Pushing image to ECR..."
docker push "${IMAGE_TAG}"
echo "    Pushed: ${IMAGE_TAG}"

echo "==> [5/5] Deploying to EC2 (${EC2_IP})..."
SSH_KEY="${SSH_KEY_PATH:-~/.ssh/sentinel.pem}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

# Wait for EC2 to be ready
echo "    Waiting for EC2 SSH to be available..."
for i in $(seq 1 30); do
  if ssh ${SSH_OPTS} -i "${SSH_KEY}" "ec2-user@${EC2_IP}" "echo ok" 2>/dev/null; then
    break
  fi
  echo "    Attempt ${i}/30, retrying in 10s..."
  sleep 10
done

# Deploy on EC2
ssh ${SSH_OPTS} -i "${SSH_KEY}" "ec2-user@${EC2_IP}" bash <<REMOTE
  set -euo pipefail

  echo "--- Logging in to ECR..."
  aws ecr get-login-password --region ${AWS_REGION} \
    | docker login --username AWS --password-stdin "${ECR_URL%/*}"

  echo "--- Pulling latest image..."
  docker pull "${IMAGE_TAG}"

  echo "--- Stopping old container (if running)..."
  docker stop sentinel-worker 2>/dev/null || true
  docker rm sentinel-worker 2>/dev/null || true

  echo "--- Starting new container..."
  docker run -d \
    --name sentinel-worker \
    --restart unless-stopped \
    --env-file /etc/sentinel/env \
    --log-driver awslogs \
    --log-opt awslogs-region=${AWS_REGION} \
    --log-opt awslogs-group=/sentinel/worker \
    --log-opt awslogs-stream=worker-\$(hostname) \
    "${IMAGE_TAG}"

  echo "--- Container started."
  docker ps --filter name=sentinel-worker
REMOTE

echo ""
echo "==> Deployment complete!"
echo "    Worker running on EC2: ${EC2_IP}"
echo "    Image: ${IMAGE_TAG}"
echo ""
echo "    To view logs:"
echo "    aws logs tail /sentinel/worker --follow --region ${AWS_REGION}"
