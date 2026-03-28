import os

# Anthropic
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Finnhub
FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]

# Google Chat — service account JSON stored as a string in env/Secrets Manager
GOOGLE_CHAT_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_CHAT_SERVICE_ACCOUNT_JSON"]
# The service account email (audience for token verification)
GOOGLE_CHAT_SERVICE_ACCOUNT_EMAIL = os.environ["GOOGLE_CHAT_SERVICE_ACCOUNT_EMAIL"]
# Project number for Google Chat event verification
GOOGLE_CLOUD_PROJECT_NUMBER = os.environ["GOOGLE_CLOUD_PROJECT_NUMBER"]

# AWS
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE_IDEAS = os.environ.get("DYNAMODB_TABLE_IDEAS", "sentinel_ideas")
DYNAMODB_TABLE_ARTICLES = os.environ.get("DYNAMODB_TABLE_ARTICLES", "sentinel_articles")
DYNAMODB_TABLE_ALERTS = os.environ.get("DYNAMODB_TABLE_ALERTS", "sentinel_alerts")

# Admin space name for system logs, e.g. "spaces/XXXXXXXXX"
SENTINEL_ADMIN_SPACE = os.environ["SENTINEL_ADMIN_SPACE"]

# Polling / Kelly tuning
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
RELEVANCE_THRESHOLD_LOW = int(os.environ.get("RELEVANCE_THRESHOLD_LOW", "8"))
RELEVANCE_THRESHOLD_MEDIUM = int(os.environ.get("RELEVANCE_THRESHOLD_MEDIUM", "6"))
RELEVANCE_THRESHOLD_HIGH = int(os.environ.get("RELEVANCE_THRESHOLD_HIGH", "4"))
FRACTIONAL_KELLY_MULTIPLIER = float(os.environ.get("FRACTIONAL_KELLY_MULTIPLIER", "0.25"))
