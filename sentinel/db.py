import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import aioboto3

from sentinel.config import AWS_REGION, DYNAMODB_TABLE_IDEAS, DYNAMODB_TABLE_ARTICLES, DYNAMODB_TABLE_ALERTS
from sentinel.models import Idea, NewsArticle, AlertRecord, NewsSensitivity


def _float_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _decimal_to_float(obj):
    """Recursively convert Decimal back to float from DynamoDB."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def to_dynamodb_item(model) -> dict:
    """Serialize a Pydantic model to a DynamoDB-compatible dict."""
    raw = json.loads(model.model_dump_json())
    return _float_to_decimal(raw)


def from_dynamodb_item(data: dict, model_class):
    """Deserialize a DynamoDB item dict to a Pydantic model."""
    clean = _decimal_to_float(data)
    return model_class.model_validate(clean)


async def save_idea(idea: Idea) -> None:
    """Save or update an Idea to DynamoDB."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        item = to_dynamodb_item(idea)
        await table.put_item(Item=item)


async def get_idea(idea_id: str) -> Optional[Idea]:
    """Retrieve a single Idea by its ID."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        response = await table.get_item(Key={"idea_id": idea_id})
        item = response.get("Item")
        if not item:
            return None
        return from_dynamodb_item(item, Idea)


async def get_all_active_ideas() -> list[Idea]:
    """Retrieve all active ideas using the GSI on is_active."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        response = await table.query(
            IndexName="is_active-index",
            KeyConditionExpression="is_active = :val",
            ExpressionAttributeValues={":val": "true"},
        )
        items = response.get("Items", [])
        return [from_dynamodb_item(item, Idea) for item in items]


async def get_ideas_for_pm(pm_slack_user_id: str) -> list[Idea]:
    """Retrieve all ideas belonging to a specific PM using the GSI."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        response = await table.query(
            IndexName="pm_slack_user_id-index",
            KeyConditionExpression="pm_slack_user_id = :val",
            ExpressionAttributeValues={":val": pm_slack_user_id},
        )
        items = response.get("Items", [])
        return [from_dynamodb_item(item, Idea) for item in items]


async def update_idea_sensitivity(idea_id: str, sensitivity: NewsSensitivity) -> None:
    """Update the news_sensitivity field of an Idea."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        await table.update_item(
            Key={"idea_id": idea_id},
            UpdateExpression="SET news_sensitivity = :val",
            ExpressionAttributeValues={":val": sensitivity.value},
        )


async def deactivate_idea(idea_id: str) -> None:
    """Mark an Idea as inactive."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_IDEAS)
        await table.update_item(
            Key={"idea_id": idea_id},
            UpdateExpression="SET is_active = :val",
            ExpressionAttributeValues={":val": "false"},
        )


async def save_article(article: NewsArticle) -> None:
    """Save a NewsArticle with TTL of 7 days after published_at."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_ARTICLES)
        item = to_dynamodb_item(article)
        # Set TTL: published_at + 7 days as Unix timestamp integer
        published_dt = article.published_at
        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        expires_at = int((published_dt + timedelta(days=7)).timestamp())
        item["expires_at"] = expires_at
        await table.put_item(Item=item)


async def article_exists(article_id: str) -> bool:
    """Check if an article already exists in DynamoDB."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_ARTICLES)
        response = await table.get_item(
            Key={"article_id": article_id},
            ProjectionExpression="article_id",
        )
        return "Item" in response


async def save_alert(alert: AlertRecord) -> None:
    """Save an AlertRecord to DynamoDB."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_ALERTS)
        item = to_dynamodb_item(alert)
        await table.put_item(Item=item)


async def update_alert_response(alert_id: str, pm_response: str, pm_custom_resize_pct: Optional[float] = None) -> None:
    """Record the PM's response to an alert."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_ALERTS)
        acknowledged_at = datetime.now(timezone.utc).isoformat()
        update_expr = "SET pm_response = :resp, acknowledged_at = :ts"
        expr_values: dict = {":resp": pm_response, ":ts": acknowledged_at}
        if pm_custom_resize_pct is not None:
            update_expr += ", pm_custom_resize_pct = :pct"
            expr_values[":pct"] = _float_to_decimal(pm_custom_resize_pct)
        await table.update_item(
            Key={"alert_id": alert_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )


async def get_recent_alerts_for_idea(idea_id: str, limit: int = 5) -> list[AlertRecord]:
    """Get the most recent alerts for a given idea using the GSI."""
    session = aioboto3.Session()
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_ALERTS)
        response = await table.query(
            IndexName="idea_id-created_at-index",
            KeyConditionExpression="idea_id = :val",
            ExpressionAttributeValues={":val": idea_id},
            ScanIndexForward=False,
            Limit=limit,
        )
        items = response.get("Items", [])
        return [from_dynamodb_item(item, AlertRecord) for item in items]
