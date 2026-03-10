"""
Test 00 — New identity with active token is provisioned to AccessGrid.

Scenario:
  - Plasec has identity 6961cb7d2c664248 ("Test Person") with one active token
  - Token is not yet in the local DB
  - run_cycle() should provision an AG card and write a sync record
"""

import pytest
import unittest
from unittest.mock import call

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, CARD_NUMBER, AG_CARD_ID, TEMPLATE_ID,
    make_mock_response,
)
from tests.fixtures import (
    IDENTITY_LIST_RESPONSE,
    IDENTITY_DETAIL_PERSON,
    TOKEN_LIST_ACTIVE,
    TOKEN_LIST_EMPTY,
)


@pytest.mark.integration
class Test00Provision(BaseSyncTest):

    def setUp(self):
        super().setUp()
        self.configure_http({
            '/identities.json':                           make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}.json':            make_mock_response(200, IDENTITY_DETAIL_PERSON),
            f'/identities/{IDENTITY_ID}/tokens.json':     make_mock_response(200, TOKEN_LIST_ACTIVE),
            # Other identities have no tokens
            '/identities/0/tokens.json':                  make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':   make_mock_response(200, TOKEN_LIST_EMPTY),
        })

    def test_00_provision_new_identity(self):
        print(f"\n[00] Provisioning new identity {IDENTITY_ID} / token {TOKEN_ID}")

        # Local DB is empty — nothing synced yet
        self.assertEqual(len(self.local_db.get_all_synced()), 0)

        metrics = self.strategies.run_cycle()

        # One card should have been provisioned
        self.assertEqual(metrics['new'], 1, "Expected 1 new card provisioned")

        # Verify AG was called with the correct data
        self.ag_client.access_cards.provision.assert_called_once()
        create_kwargs = self.ag_client.access_cards.provision.call_args.kwargs
        self.assertEqual(create_kwargs['card_template_id'], TEMPLATE_ID)
        self.assertEqual(create_kwargs['employee_id'], IDENTITY_ID)
        self.assertEqual(create_kwargs['full_name'], 'Test Person')
        self.assertEqual(create_kwargs['email'], 'test.person@example.com')
        self.assertEqual(create_kwargs['phone_number'], '555-1234')

        print(f"  AG provision called with employee_id={create_kwargs['employee_id']}, "
              f"full_name={create_kwargs['full_name']!r}")

    def test_01_sync_record_written_to_db(self):
        print(f"\n[00] Verifying local DB record after provisioning")

        self.strategies.run_cycle()

        record = self.get_db_record()
        self.assertIsNotNone(record, "Sync record should exist in local DB")
        self.assertEqual(record['plasec_identity_id'], IDENTITY_ID)
        self.assertEqual(record['plasec_token_id'], TOKEN_ID)
        self.assertEqual(record['accessgrid_card_id'], AG_CARD_ID)
        self.assertEqual(record['card_number'], CARD_NUMBER)
        self.assertEqual(record['status'], 'active')
        self.assertEqual(record['last_synced_token_status'], '1')

        print(f"  DB record: ag_card_id={record['accessgrid_card_id']}, "
              f"status={record['status']}")

    def test_02_second_cycle_does_not_reprovision(self):
        print(f"\n[00] Verifying idempotency — second cycle should not re-provision")

        self.strategies.run_cycle()
        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['new'], 0, "Should not provision again on second cycle")
        self.assertEqual(self.ag_client.access_cards.provision.call_count, 1,
                         "AG provision should only be called once")

        print("  Second cycle: no new provisions (idempotent)")

    def test_03_skip_identity_without_contact_info(self):
        print(f"\n[00] Identity with no email or phone should be skipped")

        # Override detail to have no contact info
        from tests.fixtures import IDENTITY_DETAIL_PERSON
        import copy
        no_contact = copy.deepcopy(IDENTITY_DETAIL_PERSON)
        no_contact['data']['plasecidentityEmailaddress'] = ''
        no_contact['data']['plasecidentityPhone'] = ''

        self.configure_http({
            '/identities.json':                           make_mock_response(200, IDENTITY_LIST_RESPONSE),
            f'/identities/{IDENTITY_ID}.json':            make_mock_response(200, no_contact),
            f'/identities/{IDENTITY_ID}/tokens.json':     make_mock_response(200, TOKEN_LIST_ACTIVE),
            '/identities/0/tokens.json':                  make_mock_response(200, TOKEN_LIST_EMPTY),
            '/identities/e01c265bdfc24d70/tokens.json':   make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        metrics = self.strategies.run_cycle()

        self.assertEqual(metrics['new'], 0, "Should skip identity with no contact info")
        self.ag_client.access_cards.provision.assert_not_called()

        print("  Correctly skipped identity with no email/phone")


if __name__ == '__main__':
    unittest.main()
