"""
Test 03 — Contact field changes in Plasec → AccessGrid card updated.

Scenario:
  - Identity is already synced with original name/email/phone
  - Plasec now returns different contact info for the identity
  - run_cycle() should call AG card update with changed fields only
"""

import copy
import pytest
import unittest

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, AG_CARD_ID,
    make_mock_response,
)
from tests.fixtures import (
    IDENTITY_LIST_RESPONSE,
    IDENTITY_DETAIL_PERSON,
    TOKEN_LIST_ACTIVE,
    TOKEN_LIST_EMPTY,
)


@pytest.mark.integration
class Test03FieldChanges(BaseSyncTest):

    def setUp(self):
        super().setUp()
        self.seed_synced_record(token_status='1')

    def _configure(self, detail_override=None):
        """Helper: wire HTTP mocks with optional detail override."""
        detail = detail_override or IDENTITY_DETAIL_PERSON
        self.configure_http({
            '/identities.json':                          make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}.json':           make_mock_response(200, detail),
            f'/identities/{IDENTITY_ID}/tokens.json':    make_mock_response(200, TOKEN_LIST_ACTIVE),
            '/identities/0/tokens.json':                 make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':  make_mock_response(200, TOKEN_LIST_EMPTY),
        })

    def test_00_no_update_when_fields_unchanged(self):
        print(f"\n[03] No AG update when fields haven't changed")

        self._configure()

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['field_changes'], 0)
        self.ag_client.access_cards.update.assert_not_called()

        print("  No field changes (idempotent)")

    def test_01_email_change_updates_ag_card(self):
        print(f"\n[03] Email change in Plasec → AG card updated with new email")

        changed_detail = copy.deepcopy(IDENTITY_DETAIL_PERSON)
        changed_detail['data']['plasecidentityEmailaddress'] = 'new.email@example.com'
        self._configure(changed_detail)

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['field_changes'], 1)
        self.ag_client.access_cards.update.assert_called_once_with(
            card_id=AG_CARD_ID, email='new.email@example.com'
        )

        print("  AG update called with new email")

    def test_02_phone_change_reflected_in_db(self):
        print(f"\n[03] DB should store new phone after field sync")

        changed_detail = copy.deepcopy(IDENTITY_DETAIL_PERSON)
        changed_detail['data']['plasecidentityPhone'] = '555-9999'
        self._configure(changed_detail)

        self.strategies.run_cycle()

        record = self.get_db_record()
        self.assertEqual(record['last_synced_phone'], '555-9999',
                         "DB should reflect updated phone number")

        print(f"  DB last_synced_phone={record['last_synced_phone']}")

    def test_03_name_change_updates_ag_card(self):
        print(f"\n[03] Name change in Plasec → AG card updated with new name")

        changed_detail = copy.deepcopy(IDENTITY_DETAIL_PERSON)
        changed_detail['data']['plasecFname'] = 'Updated'
        changed_detail['data']['plasecLname'] = 'Name'
        self._configure(changed_detail)

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['field_changes'], 1)
        self.ag_client.access_cards.update.assert_called_once_with(
            card_id=AG_CARD_ID, full_name='Updated Name'
        )

        print("  AG update called with new name")


if __name__ == '__main__':
    unittest.main()
