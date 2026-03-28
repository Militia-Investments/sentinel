import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Required vars — raise on missing
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BENZINGA_API_KEY = os.environ["BENZINGA_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SENTINEL_ADMIN_CHANNEL = os.environ["SENTINEL_ADMIN_CHANNEL"]

# Optional with defaults
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE_IDEAS = os.environ.get("DYNAMODB_TABLE_IDEAS", "sentinel_ideas")
DYNAMODB_TABLE_ARTICLES = os.environ.get("DYNAMODB_TABLE_ARTICLES", "sentinel_articles")
DYNAMODB_TABLE_ALERTS = os.environ.get("DYNAMODB_TABLE_ALERTS", "sentinel_alerts")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
RELEVANCE_THRESHOLD_LOW = int(os.environ.get("RELEVANCE_THRESHOLD_LOW", "8"))
RELEVANCE_THRESHOLD_MEDIUM = int(os.environ.get("RELEVANCE_THRESHOLD_MEDIUM", "6"))
RELEVANCE_THRESHOLD_HIGH = int(os.environ.get("RELEVANCE_THRESHOLD_HIGH", "4"))
FRACTIONAL_KELLY_MULTIPLIER = float(os.environ.get("FRACTIONAL_KELLY_MULTIPLIER", "0.25"))
