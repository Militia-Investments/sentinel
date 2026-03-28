import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sentinel.config import GOOGLE_CHAT_SERVICE_ACCOUNT_JSON

SCOPES = ["https://www.googleapis.com/auth/chat.bot"]

def _build_client():
    sa_info = json.loads(GOOGLE_CHAT_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build("chat", "v1", credentials=creds, cache_discovery=False)

# Module-level singleton
chat = _build_client()
