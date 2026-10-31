"""Constants and enums shared by the hub, API and CLI."""

AGENTS = {
    "claude1": "TEAM_LEADER",
    "claude2": "BACKEND_CORE",
    "claude3": "FRONTEND_MOBILE",
    "gemini": "VISUAL_OPERATOR",
    "user": "USER",
}
WORKERS = ("claude1", "claude2", "claude3", "gemini")
LEADERS = ("claude1", "user")  # may assign tasks and trigger emergency stop
BROADCAST = "ALL"

MESSAGE_TYPES = (
    "TASK_ASSIGNMENT", "TASK_ACCEPTED", "TASK_COMPLETED", "TASK_BLOCKED",
    "HELP_REQUEST", "HELP_RESPONSE", "CODE_READY", "REVIEW_REQUEST",
    "REVIEW_RESULT", "BUG_REPORT", "BUG_FIXED", "INTEGRATION_REQUEST",
    "INTEGRATION_RESULT", "TECHNICAL_DECISION", "HANDOFF", "STATUS_UPDATE",
    "SYSTEM_ALERT",
)
PRIORITIES = ("LOW", "NORMAL", "HIGH", "CRITICAL")
TASK_STATUSES = (
    "BACKLOG", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "REVIEW",
    "BLOCKED", "COMPLETED", "CANCELLED",
)
ACTIVE_TASK_STATUSES = ("ASSIGNED", "ACCEPTED", "IN_PROGRESS", "REVIEW")
MESSAGE_STATUSES = ("QUEUED", "DELIVERED", "READ", "ANSWERED", "FAILED")

MAX_CONTENT = 20_000
MAX_SUBJECT = 200
MAX_DISCUSSION_ROUNDS = 8      # messages in one conversation before escalation
MAX_DELIVERY_ATTEMPTS = 5
DEFAULT_LOCK_TTL = 900         # seconds
MAX_LOCK_TTL = 3600
ONLINE_WINDOW = 300            # seconds since last heartbeat to count as online
