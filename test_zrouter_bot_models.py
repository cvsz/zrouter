from __future__ import annotations

import unittest

import zrouter_bot
import zrouter_bot_models


class TestBotModelCompatibility(unittest.TestCase):
    def test_legacy_module_reexports_extracted_models(self):
        model_names = (
            "ApprovalCard",
            "ApprovalStatus",
            "BotMemory",
            "BotStatus",
            "CalendarEvent",
            "CartItem",
            "CloudAgent",
            "Email",
            "MediaAsset",
            "Meeting",
            "NetworkPeer",
            "Page",
            "ReviewLearning",
            "Routine",
            "RoutineStatus",
            "SharedConnector",
            "ShoppingCart",
            "SkillTemplate",
            "VaultEntry",
            "VoiceSettings",
        )
        for name in model_names:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(zrouter_bot, name),
                    getattr(zrouter_bot_models, name),
                )

    def test_approval_card_round_trip(self):
        card = zrouter_bot.ApprovalCard(
            id="approval-1",
            action="send_message",
            details="Requires operator review",
            status=zrouter_bot.ApprovalStatus.PENDING,
        )
        restored = zrouter_bot.ApprovalCard.from_dict(card.to_dict())
        self.assertEqual(restored.id, card.id)
        self.assertEqual(restored.action, card.action)
        self.assertEqual(restored.details, card.details)
        self.assertEqual(restored.status, card.status)

    def test_vault_entry_round_trip(self):
        entry = zrouter_bot.VaultEntry(
            id="vault-1",
            name="local test record",
            kind="login",
            value={"username": "test-user"},
        )
        restored = zrouter_bot.VaultEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.id, entry.id)
        self.assertEqual(restored.value, entry.value)


if __name__ == "__main__":
    unittest.main()
