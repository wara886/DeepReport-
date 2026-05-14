"""Explicit AgentMessage schema for multi-agent collaboration replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List
from uuid import uuid4


class MessageType(str, Enum):
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    CHALLENGE_CLAIM = "CHALLENGE_CLAIM"
    REQUEST_RECALCULATION = "REQUEST_RECALCULATION"
    PROPOSE_REVISION = "PROPOSE_REVISION"
    APPROVE_SECTION = "APPROVE_SECTION"
    REJECT_SECTION = "REJECT_SECTION"
    ESCALATE_CONFLICT = "ESCALATE_CONFLICT"
    STATUS_UPDATE = "STATUS_UPDATE"


class MessageStatus(str, Enum):
    CREATED = "created"
    SENT = "sent"
    HANDLED = "handled"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    sender_agent: str
    receiver_agent: str
    message_type: MessageType
    related_task_id: str = ""
    related_gap_id: str = ""
    related_claim_ids: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 3
    created_at: str = field(default_factory=lambda: now_iso())
    status: MessageStatus = MessageStatus.CREATED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender_agent": self.sender_agent,
            "receiver_agent": self.receiver_agent,
            "message_type": self.message_type.value,
            "related_task_id": self.related_task_id,
            "related_gap_id": self.related_gap_id,
            "related_claim_ids": list(self.related_claim_ids),
            "payload": dict(self.payload),
            "priority": int(self.priority),
            "created_at": self.created_at,
            "status": self.status.value,
        }

    @classmethod
    def create(
        cls,
        sender_agent: str,
        receiver_agent: str,
        message_type: MessageType,
        related_task_id: str = "",
        related_gap_id: str = "",
        related_claim_ids: List[str] | None = None,
        payload: Dict[str, Any] | None = None,
        priority: int = 3,
        status: MessageStatus = MessageStatus.CREATED,
    ) -> "AgentMessage":
        return cls(
            message_id=f"msg_{uuid4().hex[:12]}",
            sender_agent=sender_agent,
            receiver_agent=receiver_agent,
            message_type=message_type,
            related_task_id=related_task_id,
            related_gap_id=related_gap_id,
            related_claim_ids=list(related_claim_ids or []),
            payload=dict(payload or {}),
            priority=max(1, min(int(priority), 5)),
            status=status,
        )

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AgentMessage":
        return cls(
            message_id=str(payload.get("message_id", "")),
            sender_agent=str(payload.get("sender_agent", "")),
            receiver_agent=str(payload.get("receiver_agent", "")),
            message_type=parse_message_type(payload.get("message_type")),
            related_task_id=str(payload.get("related_task_id", "")),
            related_gap_id=str(payload.get("related_gap_id", "")),
            related_claim_ids=_str_list(payload.get("related_claim_ids", [])),
            payload=dict(payload.get("payload", {})) if isinstance(payload.get("payload", {}), dict) else {},
            priority=max(1, min(int(payload.get("priority", 3) or 3), 5)),
            created_at=str(payload.get("created_at") or now_iso()),
            status=parse_message_status(payload.get("status")),
        )

    def with_status(self, status: MessageStatus) -> "AgentMessage":
        return AgentMessage(
            message_id=self.message_id,
            sender_agent=self.sender_agent,
            receiver_agent=self.receiver_agent,
            message_type=self.message_type,
            related_task_id=self.related_task_id,
            related_gap_id=self.related_gap_id,
            related_claim_ids=list(self.related_claim_ids),
            payload=dict(self.payload),
            priority=self.priority,
            created_at=self.created_at,
            status=status,
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_message_type(value: Any) -> MessageType:
    text = str(value or MessageType.STATUS_UPDATE.value).strip().upper()
    return MessageType[text] if text in MessageType.__members__ else MessageType.STATUS_UPDATE


def parse_message_status(value: Any) -> MessageStatus:
    text = str(value or MessageStatus.CREATED.value).strip().lower()
    for status in MessageStatus:
        if status.value == text:
            return status
    return MessageStatus.CREATED


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
