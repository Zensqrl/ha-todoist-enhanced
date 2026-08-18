"""Constants for the Todoist Kiosk integration."""

from datetime import timedelta

DOMAIN = "todoist_kiosk"

CONF_API_TOKEN = "api_token"

API_BASE_URL = "https://api.todoist.com/api/v1"
API_PAGE_LIMIT = 200
API_REQUEST_TIMEOUT = 20
FILTER_MAX_LENGTH = 1024
QUICK_ADD_MAX_LENGTH = 2048
TASK_ID_MAX_LENGTH = 128

METADATA_UPDATE_INTERVAL = timedelta(minutes=30)

WS_TASKS = f"{DOMAIN}/tasks"
WS_FILTERS = f"{DOMAIN}/filters"
WS_COMPLETE_TASK = f"{DOMAIN}/complete_task"
WS_QUICK_ADD = f"{DOMAIN}/quick_add"
WS_REFRESH_METADATA = f"{DOMAIN}/refresh_metadata"
