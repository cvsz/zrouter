"""
zrouter_bot.py — Bot framework for zrouter.

Inspired by x.ai Grok Bot features (changelog v1.0.1, Nov 2026):
  * Auto-review rules / approval cards for sensitive actions
  * Vault credentials storage (logins, cards, contact info)
  * Memory / context import and per-bot persistence
  * Template skills and routine scheduling placeholders
  * Enhanced working status reporting

This module is importable by zrouter.py or run standalone.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

import zrouter_bot_storage as _storage
from zrouter_bot_models import (
    ApprovalCard,
    ApprovalStatus,
    BotMemory,
    BotStatus,
    CalendarEvent,
    CartItem,
    CloudAgent,
    Email,
    MediaAsset,
    Meeting,
    NetworkPeer,
    Page,
    ReviewLearning,
    Routine,
    RoutineStatus,
    SharedConnector,
    ShoppingCart,
    SkillTemplate,
    VaultEntry,
    VoiceSettings,
)

BOT_HOME = _storage.BOT_HOME
HOME = _storage.HOME
MEMORY_FILE = _storage.MEMORY_FILE
VAULT_FILE = _storage.VAULT_FILE
Memory = _storage.Memory
Vault = _storage.Vault

log = logging.getLogger("zrouter-bot")

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROUTINES_FILE = BOT_HOME / "routines.json"
SKILLS_FILE = BOT_HOME / "skills.json"

MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB (matches Grok Bot)


# --------------------------------------------------------------------------- #
# Approval / Auto-review
# --------------------------------------------------------------------------- #
class ApprovalEngine:
    """Auto-review engine: decides whether an action needs approval."""

    def __init__(self, auto_approve: set[str] | None = None) -> None:
        self._auto_approve = set(auto_approve or set())
        self._cards: dict[str, ApprovalCard] = {}
        self._lock = threading.Lock()

    def requires_approval(self, action: str) -> bool:
        return action not in self._auto_approve

    def create_card(
        self, action: str, details: str, ttl_seconds: float = 1800
    ) -> ApprovalCard:
        card = ApprovalCard(
            id=str(uuid.uuid4()),
            action=action,
            details=details,
            expires_at=time.time() + ttl_seconds,
        )
        with self._lock:
            self._cards[card.id] = card
        log.info("Approval card created: %s — %s", card.id, action)
        return card

    def approve(self, card_id: str, decided_by: str = "user") -> ApprovalCard | None:
        with self._lock:
            card = self._cards.get(card_id)
            if card is None:
                return None
            if card.status != ApprovalStatus.PENDING:
                return card
            card.status = ApprovalStatus.APPROVED
            card.decided_at = time.time()
            card.decided_by = decided_by
            return card

    def deny(self, card_id: str, decided_by: str = "user") -> ApprovalCard | None:
        with self._lock:
            card = self._cards.get(card_id)
            if card is None:
                return None
            if card.status != ApprovalStatus.PENDING:
                return card
            card.status = ApprovalStatus.DENIED
            card.decided_at = time.time()
            card.decided_by = decided_by
            return card

    def get(self, card_id: str) -> ApprovalCard | None:
        with self._lock:
            return self._cards.get(card_id)

    def list_pending(self) -> list[ApprovalCard]:
        with self._lock:
            now = time.time()
            return [
                c
                for c in self._cards.values()
                if c.status == ApprovalStatus.PENDING
                and (c.expires_at is None or c.expires_at > now)
            ]

    def expire_stale(self) -> int:
        count = 0
        now = time.time()
        with self._lock:
            for card in self._cards.values():
                if (
                    card.status == ApprovalStatus.PENDING
                    and card.expires_at is not None
                    and card.expires_at <= now
                ):
                    card.status = ApprovalStatus.EXPIRED
                    count += 1
        return count


# --------------------------------------------------------------------------- #
# Bot — main conversational agent
# --------------------------------------------------------------------------- #


class VoiceManager:
    """Manages voice settings for bots (speed slider, voice cards)."""

    def __init__(self, path: Path = BOT_HOME / "voice.json") -> None:
        self.path = path
        self._voices: dict[str, VoiceSettings] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._voices = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._voices = {k: VoiceSettings.from_dict(v) for k, v in data.items()}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load voice settings; starting empty")
            self._voices = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({k: v.to_dict() for k, v in self._voices.items()}, f, indent=2)
        os.replace(tmp, self.path)

    def get(self, bot_id: str) -> VoiceSettings:
        with self._lock:
            return self._voices.get(bot_id, VoiceSettings())

    def set(self, bot_id: str, settings: VoiceSettings) -> VoiceSettings:
        with self._lock:
            self._voices[bot_id] = settings
            self._save()
            return settings

    def set_speed(self, bot_id: str, speed: float) -> VoiceSettings:
        settings = self.get(bot_id)
        settings.speed = max(0.5, min(2.0, speed))
        return self.set(bot_id, settings)

    def set_voice(self, bot_id: str, voice_id: str) -> VoiceSettings:
        settings = self.get(bot_id)
        settings.voice_id = voice_id
        return self.set(bot_id, settings)

    def set_language(self, bot_id: str, language: str) -> VoiceSettings:
        settings = self.get(bot_id)
        settings.language = language
        return self.set(bot_id, settings)


# --------------------------------------------------------------------------- #
# Shared Connectors (x.ai: share app login as shared connector)
# --------------------------------------------------------------------------- #


class ConnectorShareManager:
    """Manages shared connectors between bots."""

    def __init__(self, path: Path = BOT_HOME / "shared_connectors.json") -> None:
        self.path = path
        self._connectors: dict[str, SharedConnector] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._connectors = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._connectors = {c["id"]: SharedConnector.from_dict(c) for c in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load shared connectors; starting empty")
            self._connectors = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self._connectors.values()], f, indent=2)
        os.replace(tmp, self.path)

    def share(
        self,
        connector_name: str,
        owner_bot_id: str,
        shared_with: list[str] | None = None,
    ) -> SharedConnector:
        connector = SharedConnector(
            id=str(uuid.uuid4()),
            connector_name=connector_name,
            owner_bot_id=owner_bot_id,
            shared_with=shared_with or [],
        )
        with self._lock:
            self._connectors[connector.id] = connector
            self._save()
        return connector

    def get(self, connector_id: str) -> SharedConnector | None:
        with self._lock:
            return self._connectors.get(connector_id)

    def list_for_bot(self, bot_id: str) -> list[SharedConnector]:
        with self._lock:
            return [
                c
                for c in self._connectors.values()
                if c.owner_bot_id == bot_id or bot_id in c.shared_with
            ]

    def share_with(self, connector_id: str, bot_id: str) -> SharedConnector | None:
        with self._lock:
            connector = self._connectors.get(connector_id)
            if connector is None:
                return None
            if bot_id not in connector.shared_with:
                connector.shared_with.append(bot_id)
                self._save()
            return connector

    def list_all(self) -> list[SharedConnector]:
        with self._lock:
            return list(self._connectors.values())


# --------------------------------------------------------------------------- #
# Review Learnings Queue (x.ai: what teammates teach waits under Review)
# --------------------------------------------------------------------------- #


class ReviewQueue:
    """Manages review learnings: what teammates teach waits for owner approval."""

    def __init__(self, path: Path = BOT_HOME / "review_queue.json") -> None:
        self.path = path
        self._reviews: dict[str, ReviewLearning] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._reviews = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._reviews = {r["id"]: ReviewLearning.from_dict(r) for r in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load review queue; starting empty")
            self._reviews = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in self._reviews.values()], f, indent=2)
        os.replace(tmp, self.path)

    def add(
        self,
        teacher_bot_id: str,
        lesson: str,
        context: str = "",
    ) -> ReviewLearning:
        review = ReviewLearning(
            id=str(uuid.uuid4()),
            teacher_bot_id=teacher_bot_id,
            lesson=lesson,
            context=context,
            status="pending",
        )
        with self._lock:
            self._reviews[review.id] = review
            self._save()
        return review

    def get(self, review_id: str) -> ReviewLearning | None:
        with self._lock:
            return self._reviews.get(review_id)

    def approve(self, review_id: str, reviewed_by: str) -> ReviewLearning | None:
        with self._lock:
            review = self._reviews.get(review_id)
            if review is None or review.status != "pending":
                return None
            review.status = "approved"
            review.reviewed_at = time.time()
            review.reviewed_by = reviewed_by
            self._save()
            return review

    def reject(self, review_id: str, reviewed_by: str) -> ReviewLearning | None:
        with self._lock:
            review = self._reviews.get(review_id)
            if review is None or review.status != "pending":
                return None
            review.status = "rejected"
            review.reviewed_at = time.time()
            review.reviewed_by = reviewed_by
            self._save()
            return review

    def list_pending(self) -> list[ReviewLearning]:
        with self._lock:
            return [r for r in self._reviews.values() if r.status == "pending"]

    def list_all(self) -> list[ReviewLearning]:
        with self._lock:
            return list(self._reviews.values())


class Bot:
    """Conversational bot with memory, vault, approvals, and status reporting."""

    def __init__(
        self,
        name: str = "zrouter-bot",
        bot_id: str | None = None,
        auto_approve: set[str] | None = None,
    ) -> None:
        self.id = bot_id or str(uuid.uuid4())
        self.name = name
        self.status = BotStatus.IDLE
        self.vault = Vault(BOT_HOME / f"vault_{self.id}.json")
        self.memory = Memory(BOT_HOME / f"memory_{self.id}.json")
        self.approval = ApprovalEngine(auto_approve)
        self.voice = VoiceManager(BOT_HOME / f"voice_{self.id}.json")
        self.connectors = ConnectorShareManager(BOT_HOME / f"connectors_{self.id}.json")
        self.reviews = ReviewQueue(BOT_HOME / f"reviews_{self.id}.json")
        self._status_lock = threading.Lock()
        self._conversations: dict[str, list[dict[str, str]]] = {}
        log.info("Bot initialized: %s (id=%s)", self.name, self.id)

    # -- status -------------------------------------------------------------
    def set_status(self, status: BotStatus) -> None:
        with self._status_lock:
            self.status = status
        log.debug("Bot %s status -> %s", self.name, status.value)

    def get_status(self) -> BotStatus:
        with self._status_lock:
            return self.status

    # -- memory -------------------------------------------------------------
    def remember(self, key: str, value: Any) -> None:
        self.memory.set(key, value)

    def recall(self, key: str, default: Any = None) -> Any:
        return self.memory.get(key, default)

    def forget(self, key: str) -> bool:
        return self.memory.delete(key)

    def all_memory(self) -> dict[str, Any]:
        return self.memory.all()

    # -- vault --------------------------------------------------------------
    def vault_add(self, entry: VaultEntry) -> VaultEntry:
        return self.vault.add(entry)

    def vault_get(self, entry_id: str) -> VaultEntry | None:
        return self.vault.get(entry_id)

    def vault_list(self) -> list[VaultEntry]:
        return self.vault.list()

    def vault_update(self, entry_id: str, value: dict[str, Any]) -> VaultEntry | None:
        return self.vault.update(entry_id, value)

    def vault_delete(self, entry_id: str) -> bool:
        return self.vault.delete(entry_id)

    # -- approvals ----------------------------------------------------------
    def request_approval(
        self, action: str, details: str, ttl_seconds: float = 1800
    ) -> ApprovalCard:
        return self.approval.create_card(action, details, ttl_seconds)

    def approve_card(
        self, card_id: str, decided_by: str = "user"
    ) -> ApprovalCard | None:
        return self.approval.approve(card_id, decided_by)

    def deny_card(self, card_id: str, decided_by: str = "user") -> ApprovalCard | None:
        return self.approval.deny(card_id, decided_by)

    def pending_approvals(self) -> list[ApprovalCard]:
        return self.approval.list_pending()

    def expire_stale_approvals(self) -> int:
        return self.approval.expire_stale()

    # -- voice controls (x.ai: voice menu speed slider, voice cards) -------
    def voice_get(self) -> VoiceSettings:
        return self.voice.get(self.id)

    def voice_set_speed(self, speed: float) -> VoiceSettings:
        return self.voice.set_speed(self.id, speed)

    def voice_set_voice(self, voice_id: str) -> VoiceSettings:
        return self.voice.set_voice(self.id, voice_id)

    def voice_set_language(self, language: str) -> VoiceSettings:
        return self.voice.set_language(self.id, language)

    # -- shared connectors (x.ai: Allow Shared Logins) ---------------------
    def connector_share(
        self, connector_name: str, shared_with: list[str] | None = None
    ) -> SharedConnector:
        return self.connectors.share(connector_name, self.id, shared_with)

    def connector_get(self, connector_id: str) -> SharedConnector | None:
        return self.connectors.get(connector_id)

    def connector_list_for_bot(self) -> list[SharedConnector]:
        return self.connectors.list_for_bot(self.id)

    def connector_share_with(
        self, connector_id: str, bot_id: str
    ) -> SharedConnector | None:
        return self.connectors.share_with(connector_id, bot_id)

    # -- review learnings (x.ai: what teammates teach waits under Review) --
    def review_add(
        self, teacher_bot_id: str, lesson: str, context: str = ""
    ) -> ReviewLearning:
        return self.reviews.add(teacher_bot_id, lesson, context)

    def review_get(self, review_id: str) -> ReviewLearning | None:
        return self.reviews.get(review_id)

    def review_approve(self, review_id: str, reviewed_by: str) -> ReviewLearning | None:
        return self.reviews.approve(review_id, reviewed_by)

    def review_reject(self, review_id: str, reviewed_by: str) -> ReviewLearning | None:
        return self.reviews.reject(review_id, reviewed_by)

    def review_list_pending(self) -> list[ReviewLearning]:
        return self.reviews.list_pending()

    def review_list_all(self) -> list[ReviewLearning]:
        return self.reviews.list_all()

    # -- conversations ------------------------------------------------------
    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        with self._status_lock:
            self._conversations.setdefault(conversation_id, []).append(
                {"role": role, "content": content, "ts": time.time()}
            )

    def get_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        with self._status_lock:
            return list(self._conversations.get(conversation_id, []))

    # -- status reporting (x.ai style short phrases) -----------------------
    def status_phrase(self) -> str:
        s = self.get_status()
        phrases = {
            BotStatus.IDLE: "Ready",
            BotStatus.WORKING: "Working on it",
            BotStatus.THINKING: "Thinking it through",
            BotStatus.WAITING_APPROVAL: "Waiting for approval",
            BotStatus.ERROR: "Something went wrong",
        }
        return phrases.get(s, "Ready")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "status_phrase": self.status_phrase(),
            "vault_entries": len(self.vault.list()),
            "memory_keys": len(self.memory.all()),
            "pending_approvals": len(self.pending_approvals()),
        }


# --------------------------------------------------------------------------- #
# Bot manager — registry of bots
# --------------------------------------------------------------------------- #
class BotManager:
    """Manages multiple bot instances."""

    def __init__(self) -> None:
        self._bots: dict[str, Bot] = {}
        self._lock = threading.Lock()

    def create(self, name: str = "zrouter-bot", bot_id: str | None = None) -> Bot:
        with self._lock:
            bid = bot_id or str(uuid.uuid4())
            bot = Bot(name=name, bot_id=bid)
            self._bots[bid] = bot
            return bot

    def get(self, bot_id: str) -> Bot | None:
        with self._lock:
            return self._bots.get(bot_id)

    def list(self) -> list[Bot]:
        with self._lock:
            return list(self._bots.values())

    def delete(self, bot_id: str) -> bool:
        with self._lock:
            if bot_id not in self._bots:
                return False
            del self._bots[bot_id]
            return True

    def default(self) -> Bot:
        with self._lock:
            if not self._bots:
                bot = Bot()
                self._bots[bot.id] = bot
                return bot
            return next(iter(self._bots.values()))


# --------------------------------------------------------------------------- #
# Module-level default manager
# --------------------------------------------------------------------------- #
MANAGER = BotManager()
DEFAULT_BOT = MANAGER.create(name="zrouter-default", bot_id="zrouter-default")


def get_bot(bot_id: str | None = None) -> Bot:
    if bot_id is None:
        return DEFAULT_BOT
    bot = MANAGER.get(bot_id)
    if bot is None:
        bot = MANAGER.create(bot_id=bot_id)
    return bot


def create_bot(name: str = "zrouter-bot", bot_id: str | None = None) -> Bot:
    return MANAGER.create(name=name, bot_id=bot_id)


# --------------------------------------------------------------------------- #
# Routine / Scheduler (x.ai: scheduled tasks, routines, cloud agents)
# --------------------------------------------------------------------------- #


class RoutineScheduler:
    """Manages scheduled routines for bots."""

    def __init__(self, path: Path = BOT_HOME / "routines.json") -> None:
        self.path = path
        self._routines: dict[str, Routine] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._routines = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._routines = {r["id"]: Routine.from_dict(r) for r in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load routines; starting empty")
            self._routines = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in self._routines.values()], f, indent=2)
        os.replace(tmp, self.path)

    def add(self, routine: Routine) -> Routine:
        with self._lock:
            self._routines[routine.id] = routine
            self._save()
            self._maybe_start()
        return routine

    def get(self, routine_id: str) -> Routine | None:
        with self._lock:
            return self._routines.get(routine_id)

    def list(self) -> list[Routine]:
        with self._lock:
            return list(self._routines.values())

    def delete(self, routine_id: str) -> bool:
        with self._lock:
            if routine_id not in self._routines:
                return False
            del self._routines[routine_id]
            self._save()
            return True

    def update(self, routine_id: str, **kwargs: Any) -> Routine | None:
        with self._lock:
            routine = self._routines.get(routine_id)
            if routine is None:
                return None
            for key, value in kwargs.items():
                if hasattr(routine, key):
                    setattr(routine, key, value)
            self._save()
            return routine

    def run_routine(self, routine: Routine, bot: Bot) -> str:
        """Execute a routine and record the result."""
        routine.status = RoutineStatus.RUNNING
        routine.last_run = time.time()
        routine.run_count += 1
        try:
            result = self._execute_action(routine.action, routine.params, bot)
            routine.status = RoutineStatus.COMPLETED
            routine.last_result = result
            routine.error_message = None
            self._save()
            return result
        except Exception as exc:  # pragma: no cover - safety net
            routine.status = RoutineStatus.FAILED
            routine.error_message = str(exc)
            log.exception("Routine %s failed", routine.id)
            self._save()
            return f"error: {exc}"
        finally:
            if routine.max_runs is not None and routine.run_count >= routine.max_runs:
                routine.status = RoutineStatus.CANCELLED
                self._save()

    def _execute_action(self, action: str, params: dict[str, Any], bot: Bot) -> str:
        """Execute a routine action. Extensible for custom action types."""
        action_lower = action.lower()
        if action_lower == "chat":
            prompt = params.get("prompt", "")
            return f"chat_executed:{prompt[:50]}..."
        if action_lower == "email_send":
            return f"email_sent:{params.get('to', 'unknown')}"
        if action_lower == "file_upload":
            path = params.get("path", "unknown")
            return f"file_uploaded:{path}"
        if action_lower == "mcp_call":
            server = params.get("server", "unknown")
            return f"mcp_called:{server}"
        if action_lower == "image_create":
            prompt = params.get("prompt", "")
            return f"image_created:{prompt[:50]}..."
        if action_lower == "video_create":
            prompt = params.get("prompt", "")
            return f"video_created:{prompt[:50]}..."
        if action_lower == "memory_import":
            source = params.get("source", "unknown")
            return f"memory_imported:{source}"
        return f"unknown_action:{action}"

    def _maybe_start(self) -> None:
        if not self._running and self._routines:
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self) -> None:  # pragma: no cover - background thread
        while self._running:
            now = time.time()
            with self._lock:
                due = [
                    r
                    for r in self._routines.values()
                    if r.status == RoutineStatus.PENDING
                    and r.next_run is not None
                    and r.next_run <= now
                ]
            for routine in due:
                bot = get_bot()
                self.run_routine(routine, bot)
            time.sleep(5)

    def shutdown(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# Template Skills (x.ai: template skills, Pages, skills guide)
# --------------------------------------------------------------------------- #


class SkillLibrary:
    """Manages reusable skill templates for bots."""

    def __init__(self, path: Path = SKILLS_FILE) -> None:
        self.path = path
        self._skills: dict[str, SkillTemplate] = {}
        self._lock = threading.Lock()
        self._load()
        self._seed_defaults()

    def _load(self) -> None:
        if not self.path.exists():
            self._skills = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._skills = {s["id"]: SkillTemplate.from_dict(s) for s in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load skill library; starting empty")
            self._skills = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in self._skills.values()], f, indent=2)
        os.replace(tmp, self.path)

    def _seed_defaults(self) -> None:
        if self._skills:
            return
        defaults = [
            SkillTemplate(
                id="skill_code_review",
                name="Code Review",
                description="Review code for bugs, security issues, and improvements",
                category="coding",
                prompt_template="Review the following code for bugs, security issues, and improvements:\n\n{code}\n\nProvide specific, actionable feedback.",
                parameters=["code"],
            ),
            SkillTemplate(
                id="skill_email_draft",
                name="Email Draft",
                description="Draft a professional email",
                category="writing",
                prompt_template="Draft a professional email to {recipient} about {subject}:\n\n{context}",
                parameters=["recipient", "subject", "context"],
            ),
            SkillTemplate(
                id="skill_research",
                name="Research",
                description="Research a topic and summarize findings",
                category="research",
                prompt_template="Research the topic '{topic}' and provide a comprehensive summary with key findings.",
                parameters=["topic"],
            ),
        ]
        for skill in defaults:
            self._skills[skill.id] = skill
        self._save()

    def add(self, skill: SkillTemplate) -> SkillTemplate:
        with self._lock:
            self._skills[skill.id] = skill
            self._save()
        return skill

    def get(self, skill_id: str) -> SkillTemplate | None:
        with self._lock:
            return self._skills.get(skill_id)

    def list(self) -> list[SkillTemplate]:
        with self._lock:
            return list(self._skills.values())

    def delete(self, skill_id: str) -> bool:
        with self._lock:
            if skill_id not in self._skills:
                return False
            del self._skills[skill_id]
            self._save()
            return True

    def use(self, skill_id: str, params: dict[str, str]) -> str:
        """Apply a skill template with parameters and return the rendered prompt."""
        skill = self.get(skill_id)
        if skill is None:
            return f"error: skill {skill_id} not found"
        try:
            rendered = skill.prompt_template.format(**params)
        except KeyError as exc:
            return f"error: missing parameter {exc}"
        skill.usage_count += 1
        return rendered


# --------------------------------------------------------------------------- #
# File Handling (x.ai: 250 MB file uploads, images, videos)
# --------------------------------------------------------------------------- #
class FileHandler:
    """Handles file uploads, images, and videos up to 250 MB."""

    MAX_BYTES: ClassVar[int] = MAX_FILE_BYTES
    ALLOWED_IMAGE_EXTENSIONS: ClassVar[set[str]] = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
    }
    ALLOWED_VIDEO_EXTENSIONS: ClassVar[set[str]] = {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
    }
    ALLOWED_DOCUMENT_EXTENSIONS: ClassVar[set[str]] = {
        ".pdf",
        ".txt",
        ".md",
        ".json",
        ".csv",
        ".docx",
    }

    def __init__(self, upload_dir: Path = BOT_HOME / "uploads") -> None:
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_file(self, filename: str, data: bytes) -> dict[str, Any]:
        """Save an uploaded file. Returns metadata dict."""
        if len(data) > self.MAX_BYTES:
            return {
                "error": f"file too large: {len(data)} bytes (max {self.MAX_BYTES})"
            }
        ext = Path(filename).suffix.lower()
        safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
        dest = self.upload_dir / safe_name
        with self._lock:
            dest.write_bytes(data)
        return {
            "id": uuid.uuid4().hex,
            "original_name": filename,
            "saved_name": safe_name,
            "path": str(dest),
            "size": len(data),
            "extension": ext,
            "is_image": ext in self.ALLOWED_IMAGE_EXTENSIONS,
            "is_video": ext in self.ALLOWED_VIDEO_EXTENSIONS,
            "is_document": ext in self.ALLOWED_DOCUMENT_EXTENSIONS,
            "created_at": time.time(),
        }

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for f in sorted(
            self.upload_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            if f.is_file():
                stat = f.stat()
                files.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "created_at": stat.st_mtime,
                        "extension": f.suffix.lower(),
                    }
                )
        return files

    def delete_file(self, file_id_or_name: str) -> bool:
        with self._lock:
            for f in self.upload_dir.iterdir():
                if f.is_file() and (
                    f.name == file_id_or_name or f.stem == file_id_or_name
                ):
                    f.unlink()
                    return True
        return False


# --------------------------------------------------------------------------- #
# Meeting / Call Integration (x.ai: Google Meet, Zoom, Teams calls)
# --------------------------------------------------------------------------- #


class MeetingManager:
    """Manages meetings that bots can join (Google Meet, Zoom, Teams)."""

    def __init__(self, path: Path = BOT_HOME / "meetings.json") -> None:
        self.path = path
        self._meetings: dict[str, Meeting] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._meetings = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._meetings = {m["id"]: Meeting.from_dict(m) for m in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load meetings; starting empty")
            self._meetings = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in self._meetings.values()], f, indent=2)
        os.replace(tmp, self.path)

    def schedule(
        self,
        title: str,
        platform: str,
        link: str,
        scheduled_at: float,
    ) -> Meeting:
        meeting = Meeting(
            id=str(uuid.uuid4()),
            title=title,
            platform=platform,
            link=link,
            status="scheduled",
            scheduled_at=scheduled_at,
        )
        with self._lock:
            self._meetings[meeting.id] = meeting
            self._save()
        return meeting

    def join(self, meeting_id: str) -> Meeting | None:
        with self._lock:
            meeting = self._meetings.get(meeting_id)
            if meeting is None:
                return None
            meeting.status = "joined"
            meeting.joined_at = time.time()
            self._save()
            return meeting

    def complete(self, meeting_id: str, summary: str) -> Meeting | None:
        with self._lock:
            meeting = self._meetings.get(meeting_id)
            if meeting is None:
                return None
            meeting.status = "completed"
            meeting.summary = summary
            self._save()
            return meeting

    def list(self) -> list[Meeting]:
        with self._lock:
            return list(self._meetings.values())


# --------------------------------------------------------------------------- #
# Voice Controls (x.ai: voice menu speed slider 0.5x-2x, voice cards)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Memory Import (x.ai: import memory from another AI assistant)
# --------------------------------------------------------------------------- #
class MemoryImporter:
    """Imports memory/context from other AI assistants or external sources."""

    @staticmethod
    def import_from_json(path: Path) -> dict[str, Any]:
        """Import memory from a JSON file exported from another assistant."""
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            return {"error": f"failed to read {path}: {exc}"}

        imported: dict[str, Any] = {}
        if isinstance(data, dict):
            for key, value in data.items():
                imported[str(key)] = value
        elif isinstance(data, list):
            for i, item in enumerate(data):
                imported[f"item_{i}"] = item

        return {"imported": len(imported), "data": imported}

    @staticmethod
    def import_from_text(path: Path) -> dict[str, Any]:
        """Import memory from a plain text file."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"error": f"failed to read {path}: {exc}"}

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        data = {f"line_{i}": line for i, line in enumerate(lines)}
        return {"imported": len(data), "data": data}


# --------------------------------------------------------------------------- #
# Status / Health Reporting (x.ai: status line, working status)
# --------------------------------------------------------------------------- #
class BotHealth:
    """Reports bot health and diagnostics."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    def report(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot.id,
            "bot_name": self.bot.name,
            "status": self.bot.get_status().value,
            "status_phrase": self.bot.status_phrase(),
            "uptime_seconds": time.time()
            - self.bot.memory.get("started_at", time.time()),
            "vault_entries": len(self.bot.vault.list()),
            "memory_keys": len(self.bot.memory.all()),
            "pending_approvals": len(self.bot.pending_approvals()),
            "max_file_bytes": MAX_FILE_BYTES,
            "supported_image_extensions": sorted(FileHandler.ALLOWED_IMAGE_EXTENSIONS),
            "supported_video_extensions": sorted(FileHandler.ALLOWED_VIDEO_EXTENSIONS),
            "supported_document_extensions": sorted(
                FileHandler.ALLOWED_DOCUMENT_EXTENSIONS
            ),
        }


# --------------------------------------------------------------------------- #
# Pages (x.ai: collaborative documents - reports, memos, dashboards)
# --------------------------------------------------------------------------- #


class PageManager:
    """Manages collaborative Pages for bots (x.ai: Pages - reports, memos, dashboards)."""

    def __init__(self, path: Path = BOT_HOME / "pages.json") -> None:
        self.path = path
        self._pages: dict[str, Page] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._pages = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._pages = {p["id"]: Page.from_dict(p) for p in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load pages; starting empty")
            self._pages = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in self._pages.values()], f, indent=2)
        os.replace(tmp, self.path)

    def create(
        self,
        title: str,
        content: str,
        owner_bot_id: str,
        shared_with: list[str] | None = None,
    ) -> Page:
        page = Page(
            id=str(uuid.uuid4()),
            title=title,
            content=content,
            owner_bot_id=owner_bot_id,
            shared_with=shared_with or [],
        )
        with self._lock:
            self._pages[page.id] = page
            self._save()
        return page

    def get(self, page_id: str) -> Page | None:
        with self._lock:
            return self._pages.get(page_id)

    def update(self, page_id: str, content: str | None = None) -> Page | None:
        with self._lock:
            page = self._pages.get(page_id)
            if page is None:
                return None
            if content is not None:
                page.content = content
                page.updated_at = time.time()
                self._save()
            return page

    def share_with(self, page_id: str, bot_id: str) -> Page | None:
        with self._lock:
            page = self._pages.get(page_id)
            if page is None:
                return None
            if bot_id not in page.shared_with:
                page.shared_with.append(bot_id)
                page.updated_at = time.time()
                self._save()
            return page

    def list_for_bot(self, bot_id: str) -> list[Page]:
        with self._lock:
            return [
                p
                for p in self._pages.values()
                if p.owner_bot_id == bot_id or bot_id in p.shared_with
            ]

    def delete(self, page_id: str) -> bool:
        with self._lock:
            if page_id not in self._pages:
                return False
            del self._pages[page_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Cloud Agents (x.ai: cloud agents - background task agents)
# --------------------------------------------------------------------------- #


class CloudAgentManager:
    """Manages cloud agents that run background tasks."""

    def __init__(self, path: Path = BOT_HOME / "cloud_agents.json") -> None:
        self.path = path
        self._agents: dict[str, CloudAgent] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._agents = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._agents = {a["id"]: CloudAgent.from_dict(a) for a in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load cloud agents; starting empty")
            self._agents = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([a.to_dict() for a in self._agents.values()], f, indent=2)
        os.replace(tmp, self.path)

    def create(self, name: str, mode: str, task: str) -> CloudAgent:
        agent = CloudAgent(
            id=str(uuid.uuid4()),
            name=name,
            mode=mode,
            status="idle",
            task=task,
        )
        with self._lock:
            self._agents[agent.id] = agent
            self._save()
        return agent

    def get(self, agent_id: str) -> CloudAgent | None:
        with self._lock:
            return self._agents.get(agent_id)

    def list(self) -> list[CloudAgent]:
        with self._lock:
            return list(self._agents.values())

    def start(self, agent_id: str) -> CloudAgent | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            agent.status = "running"
            agent.started_at = time.time()
            self._save()
            return agent

    def complete(self, agent_id: str, result: str) -> CloudAgent | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            agent.status = "completed"
            agent.result = result
            agent.completed_at = time.time()
            self._save()
            return agent

    def fail(self, agent_id: str, error: str) -> CloudAgent | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            agent.status = "failed"
            agent.result = f"error: {error}"
            agent.completed_at = time.time()
            self._save()
            return agent

    def delete(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Email Forwarding (x.ai: email forwarding)
# --------------------------------------------------------------------------- #


class EmailManager:
    """Manages email forwarding for bots."""

    def __init__(self, path: Path = BOT_HOME / "emails.json") -> None:
        self.path = path
        self._emails: dict[str, Email] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._emails = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._emails = {e["id"]: Email.from_dict(e) for e in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load emails; starting empty")
            self._emails = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self._emails.values()], f, indent=2)
        os.replace(tmp, self.path)

    def draft(
        self,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
    ) -> Email:
        email = Email(
            id=str(uuid.uuid4()),
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body=body,
            status="draft",
        )
        with self._lock:
            self._emails[email.id] = email
            self._save()
        return email

    def send(self, email_id: str) -> Email | None:
        with self._lock:
            email = self._emails.get(email_id)
            if email is None:
                return None
            email.status = "sent"
            email.sent_at = time.time()
            self._save()
            return email

    def get(self, email_id: str) -> Email | None:
        with self._lock:
            return self._emails.get(email_id)

    def list(self) -> list[Email]:
        with self._lock:
            return list(self._emails.values())

    def delete(self, email_id: str) -> bool:
        with self._lock:
            if email_id not in self._emails:
                return False
            del self._emails[email_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Calendar Integration (x.ai: Google Calendar, Outlook Calendar)
# --------------------------------------------------------------------------- #


class CalendarManager:
    """Manages calendar events for bots (Google Calendar, Outlook Calendar)."""

    def __init__(self, path: Path = BOT_HOME / "calendar.json") -> None:
        self.path = path
        self._events: dict[str, CalendarEvent] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._events = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._events = {e["id"]: CalendarEvent.from_dict(e) for e in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load calendar events; starting empty")
            self._events = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self._events.values()], f, indent=2)
        os.replace(tmp, self.path)

    def create(
        self,
        title: str,
        start_time: float,
        end_time: float,
        description: str,
        attendees: list[str] | None = None,
    ) -> CalendarEvent:
        event = CalendarEvent(
            id=str(uuid.uuid4()),
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            attendees=attendees or [],
            status="scheduled",
        )
        with self._lock:
            self._events[event.id] = event
            self._save()
        return event

    def get(self, event_id: str) -> CalendarEvent | None:
        with self._lock:
            return self._events.get(event_id)

    def list(self) -> list[CalendarEvent]:
        with self._lock:
            return list(self._events.values())

    def cancel(self, event_id: str) -> CalendarEvent | None:
        with self._lock:
            event = self._events.get(event_id)
            if event is None:
                return None
            event.status = "cancelled"
            self._save()
            return event

    def delete(self, event_id: str) -> bool:
        with self._lock:
            if event_id not in self._events:
                return False
            del self._events[event_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Image/Video Creation (x.ai: image and video creation)
# --------------------------------------------------------------------------- #


class MediaManager:
    """Manages generated images and videos for bots."""

    def __init__(self, media_dir: Path = BOT_HOME / "media") -> None:
        self.path = BOT_HOME / "media.json"
        self.media_dir = media_dir
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._assets: dict[str, MediaAsset] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._assets = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._assets = {a["id"]: MediaAsset.from_dict(a) for a in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load media assets; starting empty")
            self._assets = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([a.to_dict() for a in self._assets.values()], f, indent=2)
        os.replace(tmp, self.path)

    def create(
        self,
        title: str,
        media_type: str,
        prompt: str,
        file_path: str,
        size_bytes: int,
    ) -> MediaAsset:
        asset = MediaAsset(
            id=str(uuid.uuid4()),
            title=title,
            media_type=media_type,
            prompt=prompt,
            file_path=file_path,
            size_bytes=size_bytes,
        )
        with self._lock:
            self._assets[asset.id] = asset
            self._save()
        return asset

    def get(self, asset_id: str) -> MediaAsset | None:
        with self._lock:
            return self._assets.get(asset_id)

    def list(self) -> list[MediaAsset]:
        with self._lock:
            return list(self._assets.values())

    def delete(self, asset_id: str) -> bool:
        with self._lock:
            if asset_id not in self._assets:
                return False
            asset = self._assets[asset_id]
            try:
                Path(asset.file_path).unlink(missing_ok=True)
            except OSError:
                pass
            del self._assets[asset_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Shopping Cart / Checkout (x.ai: shopping cards, checkout)
# --------------------------------------------------------------------------- #


class CartManager:
    """Manages shopping carts for bots (x.ai: shopping cards, checkout)."""

    def __init__(self, path: Path = BOT_HOME / "carts.json") -> None:
        self.path = path
        self._carts: dict[str, ShoppingCart] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._carts = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._carts = {c["id"]: ShoppingCart.from_dict(c) for c in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load carts; starting empty")
            self._carts = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self._carts.values()], f, indent=2)
        os.replace(tmp, self.path)

    def create(self, owner_bot_id: str) -> ShoppingCart:
        cart = ShoppingCart(
            id=str(uuid.uuid4()),
            owner_bot_id=owner_bot_id,
            items=[],
            status="active",
        )
        with self._lock:
            self._carts[cart.id] = cart
            self._save()
        return cart

    def get(self, cart_id: str) -> ShoppingCart | None:
        with self._lock:
            return self._carts.get(cart_id)

    def list_for_bot(self, bot_id: str) -> list[ShoppingCart]:
        with self._lock:
            return [c for c in self._carts.values() if c.owner_bot_id == bot_id]

    def add_item(
        self,
        cart_id: str,
        product_name: str,
        price: float,
        quantity: int,
        url: str,
    ) -> ShoppingCart | None:
        with self._lock:
            cart = self._carts.get(cart_id)
            if cart is None:
                return None
            item = CartItem(
                id=str(uuid.uuid4()),
                product_name=product_name,
                price=price,
                quantity=quantity,
                url=url,
            )
            cart.items.append(item)
            self._save()
            return cart

    def checkout(self, cart_id: str) -> ShoppingCart | None:
        with self._lock:
            cart = self._carts.get(cart_id)
            if cart is None:
                # Try prefix match
                matches = [
                    c for c_id, c in self._carts.items() if c_id.startswith(cart_id)
                ]
                if len(matches) == 1:
                    cart = matches[0]
                else:
                    return None
            cart.status = "checked_out"
            cart.checked_out_at = time.time()
            self._save()
            return cart

    def delete(self, cart_id: str) -> bool:
        with self._lock:
            if cart_id not in self._carts:
                return False
            del self._carts[cart_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Tailscale / Private Network (x.ai: Tailscale plugin, private networks)
# --------------------------------------------------------------------------- #


class NetworkManager:
    """Manages private network peers (Tailscale, route traffic)."""

    def __init__(self, path: Path = BOT_HOME / "network.json") -> None:
        self.path = path
        self._peers: dict[str, NetworkPeer] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._peers = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._peers = {p["id"]: NetworkPeer.from_dict(p) for p in data}
        except (OSError, ValueError, KeyError):
            log.exception("Failed to load network peers; starting empty")
            self._peers = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in self._peers.values()], f, indent=2)
        os.replace(tmp, self.path)

    def add_peer(
        self,
        name: str,
        ip: str,
        status: str = "online",
    ) -> NetworkPeer:
        peer = NetworkPeer(
            id=str(uuid.uuid4()),
            name=name,
            ip=ip,
            status=status,
            last_seen=time.time() if status == "online" else None,
        )
        with self._lock:
            self._peers[peer.id] = peer
            self._save()
        return peer

    def get(self, peer_id: str) -> NetworkPeer | None:
        with self._lock:
            return self._peers.get(peer_id)

    def list(self) -> list[NetworkPeer]:
        with self._lock:
            return list(self._peers.values())

    def update_status(self, peer_id: str, status: str) -> NetworkPeer | None:
        with self._lock:
            peer = self._peers.get(peer_id)
            if peer is None:
                matches = [
                    p for p_id, p in self._peers.items() if p_id.startswith(peer_id)
                ]
                if len(matches) == 1:
                    peer = matches[0]
                else:
                    return None
            peer.status = status
            if status == "online":
                peer.last_seen = time.time()
            self._save()
            return peer

    def delete(self, peer_id: str) -> bool:
        with self._lock:
            if peer_id not in self._peers:
                return False
            del self._peers[peer_id]
            self._save()
            return True


# --------------------------------------------------------------------------- #
# Extended __all__
# --------------------------------------------------------------------------- #
__all__ = [
    "DEFAULT_BOT",
    "MANAGER",
    "MAX_FILE_BYTES",
    "ApprovalCard",
    "ApprovalEngine",
    "ApprovalStatus",
    "Bot",
    "BotHealth",
    "BotManager",
    "BotMemory",
    "BotStatus",
    "CalendarEvent",
    "CalendarManager",
    "CartItem",
    "CartManager",
    "CloudAgent",
    "CloudAgentManager",
    "ConnectorShareManager",
    "Email",
    "EmailManager",
    "FileHandler",
    "MediaAsset",
    "MediaManager",
    "Meeting",
    "MeetingManager",
    "Memory",
    "MemoryImporter",
    "NetworkManager",
    "NetworkPeer",
    "Page",
    "PageManager",
    "ReviewLearning",
    "ReviewQueue",
    "Routine",
    "RoutineScheduler",
    "RoutineStatus",
    "SharedConnector",
    "ShoppingCart",
    "SkillLibrary",
    "SkillTemplate",
    "Vault",
    "VaultEntry",
    "VoiceManager",
    "VoiceSettings",
    "create_bot",
    "get_bot",
]
