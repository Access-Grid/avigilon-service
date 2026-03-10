"""
Test 02 — Identity or token deleted from Plasec → AG card terminated.

Scenarios:
  - Identity 6961cb7d2c664248 disappears from Plasec → AG card deleted, DB marked deleted
  - Identity still present but token 54a67bf3a2944214 is gone → AG card deleted
  - Both identity and token still present → no deletion (idempotent)
"""

import pytest
import unittest

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, AG_CARD_ID,
    make_mock_response,
)
from tests.fixtures import (
    IDENTITY_LIST_RESPONSE,
    IDENTITY_LIST_PERSON_INACTIVE,
    TOKEN_LIST_ACTIVE,
    TOKEN_LIST_EMPTY,
)


@pytest.mark.integration
class Test02Deletion(BaseSyncTest):

    def setUp(self):
        super().setUp()
        self.seed_synced_record(token_status='1')

    def test_00_identity_deleted_terminates_ag_card(self):
        print(f"\n[02] Identity {IDENTITY_ID} gone from Plasec — AG card should be deleted")

        # Identity list no longer contains Person, Test
        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_PERSON_INACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['deleted'], 1, "Expected 1 identity deletion")
        self.ag_client.access_cards.delete.assert_called_once_with(card_id=AG_CARD_ID)

        print(f"  AG delete called for card {AG_CARD_ID}")

    def test_01_db_marked_deleted_after_identity_gone(self):
        print(f"\n[02] DB record should be marked deleted after identity removed from Plasec")

        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_PERSON_INACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        self.strategies.run_cycle()

        record = self.get_db_record()
        self.assertEqual(record['status'], 'deleted', "DB record should be marked deleted")

        print(f"  DB status={record['status']}")

    def test_02_token_deleted_terminates_ag_card(self):
        print(f"\n[02] Token {TOKEN_ID} gone from Plasec — AG card should be deleted")

        # Identity still exists but token list is empty
        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['orphaned'], 1, "Expected 1 orphaned token deletion")
        self.ag_client.access_cards.delete.assert_called_once_with(card_id=AG_CARD_ID)

        print(f"  AG delete called for orphaned card {AG_CARD_ID}")

    def test_03_no_delete_when_identity_and_token_present(self):
        print(f"\n[02] No delete when both identity and token still exist")

        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_ACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['deleted'], 0)
        self.assertEqual(metrics['orphaned'], 0)
        self.ag_client.access_cards.delete.assert_not_called()

        print("  No deletions when data is present (idempotent)")


if __name__ == '__main__':
    unittest.main()
