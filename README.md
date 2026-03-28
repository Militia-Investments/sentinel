# sentinel

The build is complete and clean. Here's what was delivered:

SENTINEL MVP — Build Complete
59/59 unit tests passing. All files match the spec exactly.

What was built (35 files):
Layer	Files
Models	sentinel/models.py — all Pydantic v2 models, spec-exact field names
Config	sentinel/config.py — env var loading, fails fast on missing required vars
Database	sentinel/db.py — 11 async DynamoDB functions via aioboto3, Decimal handling, TTL on articles
News	benzinga.py, edgar.py, gdelt.py, poller.py — all 3 sources, dedup, parallel polling
Analysis	relevance.py (Haiku), impact.py (Sonnet), kelly.py (pure math, quarter-Kelly, capped)
Slack	alerts.py (Block Kit), onboarding.py (13-step flow), sensitivity.py, bot.py
Worker	worker/main.py — two async loops, structlog JSON, heartbeat
Tests	test_kelly.py (17 unit), test_slack_alerts.py (42 unit), test_relevance.py + test_impact.py (integration, need real API key)
Infra	main.tf (539 lines: EC2, DynamoDB x3, IAM, ECR, CloudWatch, Secrets Manager), outputs.tf, variables.tf, deploy.sh
Docker	Dockerfile
Next steps to go live:
Copy .env.example → .env, fill in real API keys
terraform apply in infra/terraform/
Populate Secrets Manager values on AWS
bash infra/deploy.sh
Run the manual smoke test checklist from the spe