"""
Test 01 — Plasec token status changes → AccessGrid card updated.

Scenario:
  - Identity and token are already synced (in local DB as active, status "1")
  - Plasec now returns the token with status "2" (Inactive)
  - run_cycle() should suspend the AG card and update the DB
"""

import pytest
import unittest

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, AG_CARD_ID,
    make_mock_response,
)
from tests.fixtures import (
    IDENTITY_LIST_RESPONSE,
    TOKEN_LIST_ACTIVE,
    TOKEN_LIST_INACTIVE,
    TOKEN_LIST_EMPTY,
)


@pytest.mark.integration
class Test01PlasecStatusChange(BaseSyncTest):

    def setUp(self):
        super().setUp()
        # Pre-seed the DB as if test_00 already ran
        self.seed_synced_record(token_status='1')

    def test_00_token_goes_inactive_suspends_ag_card(self):
        print(f"\n[01] Plasec token {TOKEN_ID} changes to Inactive (status 2)")

        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_INACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['status_changes'], 1, "Expected 1 status change")
        self.ag_client.access_cards.suspend.assert_called_once_with(card_id=AG_CARD_ID)

        print(f"  AG suspend called for card {AG_CARD_ID}")

    def test_01_db_reflects_new_status(self):
        print(f"\n[01] Verifying DB updated after status change")

        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_INACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        self.strategies.run_cycle()

        record = self.get_db_record()
        self.assertEqual(record['last_synced_token_status'], '2',
                         "DB should reflect new Plasec status")

        print(f"  DB last_synced_token_status={record['last_synced_token_status']}")

    def test_02_no_change_when_status_unchanged(self):
        print(f"\n[01] No AG call when token status hasn't changed")

        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_ACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['status_changes'], 0)
        self.ag_client.access_cards.suspend.assert_not_called()

        print("  No AG calls when status unchanged (idempotent)")

    def test_03_token_reactivated_activates_ag_card(self):
        print(f"\n[01] Plasec token reactivated — AG card should be activated")

        # Seed the DB as suspended
        self.local_db._conn.execute(
            "UPDATE ag_sync_state SET last_synced_token_status = '2' "
            "WHERE plasec_identity_id = ? AND plasec_token_id = ?",
            (IDENTITY_ID, TOKEN_ID)
        )
        self.local_db._conn.commit()

        # Plasec now shows token active again
        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_ACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['status_changes'], 1)
        self.ag_client.access_cards.resume.assert_called_once_with(card_id=AG_CARD_ID)

        print(f"  AG resume called for card {AG_CARD_ID}")


if __name__ == '__main__':
    unittest.main()
