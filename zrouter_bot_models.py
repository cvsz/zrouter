"""Public bot domain models, enums, and serialization contracts."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class BotStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    THINKING = "thinking"
    WAITING_APPROVAL = "waiting_approval"
    ERROR = "error"


@dataclass
class ApprovalCard:
    id: str
    action: str
    details: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    decided_at: float | None = None
    decided_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApprovalCard:
        return cls(
            id=d["id"],
            action=d["action"],
            details=d["details"],
            status=ApprovalStatus(d.get("status", "pending")),
            created_at=d.get("created_at", time.time()),
            expires_at=d.get("expires_at"),
            decided_at=d.get("decided_at"),
            decided_by=d.get("decided_by"),
        )


@dataclass
class VaultEntry:
    id: str
    name: str
    kind: str  # login, card, contact, secret
    value: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VaultEntry:
        return cls(
            id=d["id"],
            name=d["name"],
            kind=d["kind"],
            value=d["value"],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class BotMemory:
    key: str
    value: Any
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BotMemory:
        return cls(
            key=d["key"], value=d["value"], updated_at=d.get("updated_at", time.time())
        )


# --------------------------------------------------------------------------- #
# Vault — credential storage
# --------------------------------------------------------------------------- #


@dataclass
class VoiceSettings:
    """Voice settings for a bot (x.ai voice menu: speed slider, voice selection)."""

    voice_id: str = "default"
    speed: float = 1.0  # 0.5x to 2.0x
    language: str = "en"

    def __post_init__(self) -> None:
        self.speed = max(0.5, min(2.0, self.speed))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VoiceSettings:
        return cls(
            voice_id=d.get("voice_id", "default"),
            speed=d.get("speed", 1.0),
            language=d.get("language", "en"),
        )


@dataclass
class SharedConnector:
    """A connector shared between bots (x.ai: shared connector, Allow Shared Logins)."""

    id: str
    connector_name: str
    owner_bot_id: str
    shared_with: list[str]  # bot_ids that can use this connector
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SharedConnector:
        return cls(
            id=d["id"],
            connector_name=d["connector_name"],
            owner_bot_id=d["owner_bot_id"],
            shared_with=d.get("shared_with", []),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class ReviewLearning:
    """A learning item that a teammate taught, waiting for owner/Manager approval."""

    id: str
    teacher_bot_id: str
    lesson: str  # what was taught
    context: str  # where/how it was taught
    status: str  # "pending", "approved", "rejected"
    created_at: float = field(default_factory=time.time)
    reviewed_at: float | None = None
    reviewed_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReviewLearning:
        return cls(
            id=d["id"],
            teacher_bot_id=d["teacher_bot_id"],
            lesson=d["lesson"],
            context=d.get("context", ""),
            status=d.get("status", "pending"),
            created_at=d.get("created_at", time.time()),
            reviewed_at=d.get("reviewed_at"),
            reviewed_by=d.get("reviewed_by"),
        )


class RoutineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Routine:
    """A scheduled routine that runs automatically on a cron-like schedule."""

    id: str
    name: str
    action: str  # e.g. "chat", "file_upload", "email_send", "mcp_call"
    params: dict[str, Any]
    schedule: str  # e.g. "every 1 hour", "daily 09:00", "cron */5 * * * *"
    status: RoutineStatus = RoutineStatus.PENDING
    next_run: float | None = None
    last_run: float | None = None
    run_count: int = 0
    max_runs: int | None = None
    created_at: float = field(default_factory=time.time)
    last_result: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Routine:
        return cls(
            id=d["id"],
            name=d["name"],
            action=d["action"],
            params=d["params"],
            schedule=d["schedule"],
            status=RoutineStatus(d.get("status", "pending")),
            next_run=d.get("next_run"),
            last_run=d.get("last_run"),
            run_count=d.get("run_count", 0),
            max_runs=d.get("max_runs"),
            created_at=d.get("created_at", time.time()),
            last_result=d.get("last_result"),
            error_message=d.get("error_message"),
        )


@dataclass
class SkillTemplate:
    """A reusable skill template for bots."""

    id: str
    name: str
    description: str
    category: str  # e.g. "coding", "research", "writing", "analysis"
    prompt_template: str
    parameters: list[str]  # parameter names
    created_at: float = field(default_factory=time.time)
    usage_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SkillTemplate:
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            category=d["category"],
            prompt_template=d["prompt_template"],
            parameters=d.get("parameters", []),
            created_at=d.get("created_at", time.time()),
            usage_count=d.get("usage_count", 0),
        )


@dataclass
class Meeting:
    """Represents a meeting that a bot can join."""

    id: str
    title: str
    platform: str  # "google_meet", "zoom", "microsoft_teams"
    link: str
    status: str  # "scheduled", "joined", "completed", "failed"
    scheduled_at: float
    joined_at: float | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Meeting:
        return cls(
            id=d["id"],
            title=d["title"],
            platform=d["platform"],
            link=d["link"],
            status=d["status"],
            scheduled_at=d["scheduled_at"],
            joined_at=d.get("joined_at"),
            summary=d.get("summary"),
        )


@dataclass
class Page:
    """A collaborative document/page (x.ai: Pages - reports, memos, dashboards)."""

    id: str
    title: str
    content: str
    owner_bot_id: str
    shared_with: list[str]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Page:
        return cls(
            id=d["id"],
            title=d["title"],
            content=d["content"],
            owner_bot_id=d["owner_bot_id"],
            shared_with=d.get("shared_with", []),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class CloudAgent:
    """A cloud agent that runs background tasks (x.ai: cloud agents)."""

    id: str
    name: str
    mode: str  # e.g. "code", "research", "analysis", "writing"
    status: str  # "idle", "running", "completed", "failed"
    task: str | None = None
    result: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CloudAgent:
        return cls(
            id=d["id"],
            name=d["name"],
            mode=d["mode"],
            status=d["status"],
            task=d.get("task"),
            result=d.get("result"),
            created_at=d.get("created_at", time.time()),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
        )


@dataclass
class Email:
    """Represents an email that a bot can forward."""

    id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    status: str  # "draft", "sent", "failed"
    created_at: float = field(default_factory=time.time)
    sent_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Email:
        return cls(
            id=d["id"],
            from_addr=d["from_addr"],
            to_addr=d["to_addr"],
            subject=d["subject"],
            body=d["body"],
            status=d.get("status", "draft"),
            created_at=d.get("created_at", time.time()),
            sent_at=d.get("sent_at"),
        )


@dataclass
class CalendarEvent:
    """Represents a calendar event."""

    id: str
    title: str
    start_time: float
    end_time: float
    description: str
    attendees: list[str]
    status: str  # "scheduled", "confirmed", "cancelled"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CalendarEvent:
        return cls(
            id=d["id"],
            title=d["title"],
            start_time=d["start_time"],
            end_time=d["end_time"],
            description=d["description"],
            attendees=d.get("attendees", []),
            status=d.get("status", "scheduled"),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class MediaAsset:
    """Represents a generated image or video."""

    id: str
    title: str
    media_type: str  # "image" or "video"
    prompt: str
    file_path: str
    size_bytes: int
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MediaAsset:
        return cls(
            id=d["id"],
            title=d["title"],
            media_type=d["media_type"],
            prompt=d["prompt"],
            file_path=d["file_path"],
            size_bytes=d["size_bytes"],
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class CartItem:
    """An item in a shopping cart."""

    id: str
    product_name: str
    price: float
    quantity: int
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CartItem:
        return cls(
            id=d["id"],
            product_name=d["product_name"],
            price=d["price"],
            quantity=d["quantity"],
            url=d["url"],
        )


@dataclass
class ShoppingCart:
    """A shopping cart for a bot."""

    id: str
    owner_bot_id: str
    items: list[CartItem]
    status: str = "active"  # "active", "checked_out", "abandoned"
    created_at: float = field(default_factory=time.time)
    checked_out_at: float | None = None

    def total(self) -> float:
        return sum(item.price * item.quantity for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShoppingCart:
        return cls(
            id=d["id"],
            owner_bot_id=d["owner_bot_id"],
            items=[CartItem.from_dict(i) for i in d.get("items", [])],
            status=d.get("status", "active"),
            created_at=d.get("created_at", time.time()),
            checked_out_at=d.get("checked_out_at"),
        )


@dataclass
class NetworkPeer:
    """A peer in a private network (Tailscale)."""

    id: str
    name: str
    ip: str
    status: str  # "online", "offline", "connecting"
    last_seen: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkPeer:
        return cls(
            id=d["id"],
            name=d["name"],
            ip=d["ip"],
            status=d["status"],
            last_seen=d.get("last_seen"),
        )
