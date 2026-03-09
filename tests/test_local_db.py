"""
Unit tests for LocalDB — CRUD, state transitions, error tracking.
"""

import pytest
import unittest

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, AG_CARD_ID, CARD_NUMBER,
)


@pytest.mark.unit
class TestLocalDB(BaseSyncTest):
    """LocalDB CRUD and state machine tests (in-memory SQLite)."""

    def test_initially_empty(self):
        self.assertEqual(len(self.local_db.get_all_synced()), 0)
        self.assertTrue(self.local_db.is_empty())

    def test_record_sync_creates_record(self):
        self.local_db.record_sync(
            identity_id=IDENTITY_ID,
            token_id=TOKEN_ID,
            ag_card_id=AG_CARD_ID,
            card_number=CARD_NUMBER,
            full_name='Test Person',
            email='test@example.com',
            phone='555-1234',
            token_status='1',
        )

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertIsNotNone(record)
        self.assertEqual(record['accessgrid_card_id'], AG_CARD_ID)
        self.assertEqual(record['card_number'], CARD_NUMBER)
        self.assertEqual(record['full_name'], 'Test Person')
        self.assertEqual(record['last_synced_email'], 'test@example.com')
        self.assertEqual(record['last_synced_phone'], '555-1234')
        self.assertEqual(record['last_synced_token_status'], '1')
        self.assertEqual(record['status'], 'active')
        self.assertEqual(record['retry_count'], 0)

    def test_record_sync_is_idempotent(self):
        """Calling record_sync twice on the same key updates rather than duplicating."""
        self.local_db.record_sync(
            identity_id=IDENTITY_ID, token_id=TOKEN_ID,
            ag_card_id=AG_CARD_ID, card_number=CARD_NUMBER,
            full_name='First Name', email='first@example.com', phone='111',
            token_status='1',
        )
        self.local_db.record_sync(
            identity_id=IDENTITY_ID, token_id=TOKEN_ID,
            ag_card_id=AG_CARD_ID, card_number=CARD_NUMBER,
            full_name='Second Name', email='second@example.com', phone='222',
            token_status='1',
        )

        records = self.local_db.get_all_synced()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['full_name'], 'Second Name')

    def test_get_synced_identity_token_pairs(self):
        self.seed_synced_record()
        pairs = self.local_db.get_synced_identity_token_pairs()
        self.assertIn((IDENTITY_ID, TOKEN_ID), pairs)

    def test_get_synced_pairs_excludes_deleted(self):
        self.seed_synced_record()
        self.local_db.mark_deleted(IDENTITY_ID, TOKEN_ID)

        pairs = self.local_db.get_synced_identity_token_pairs()
        self.assertNotIn((IDENTITY_ID, TOKEN_ID), pairs)

    def test_get_active_synced_excludes_deleted(self):
        self.seed_synced_record()
        self.local_db.mark_deleted(IDENTITY_ID, TOKEN_ID)

        active = self.local_db.get_active_synced()
        self.assertEqual(len(active), 0)

    def test_get_active_synced_returns_active_records(self):
        self.seed_synced_record()
        active = self.local_db.get_active_synced()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['plasec_identity_id'], IDENTITY_ID)

    def test_update_token_status_seen(self):
        self.seed_synced_record(token_status='1')
        self.local_db.update_token_status_seen(IDENTITY_ID, TOKEN_ID, '2')

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertEqual(record['last_synced_token_status'], '2')

    def test_update_status(self):
        self.seed_synced_record()
        self.local_db.update_status(IDENTITY_ID, TOKEN_ID, 'suspended')

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertEqual(record['status'], 'suspended')

    def test_update_field_snapshot(self):
        self.seed_synced_record()
        self.local_db.update_field_snapshot(
            IDENTITY_ID, TOKEN_ID, 'New Name', 'new@example.com', '999-9999'
        )

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertEqual(record['full_name'], 'New Name')
        self.assertEqual(record['last_synced_email'], 'new@example.com')
        self.assertEqual(record['last_synced_phone'], '999-9999')

    def test_mark_deleted(self):
        self.seed_synced_record()
        self.local_db.mark_deleted(IDENTITY_ID, TOKEN_ID)

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertEqual(record['status'], 'deleted')

    def test_get_by_ag_card_id(self):
        self.seed_synced_record()
        record = self.local_db.get_by_ag_card_id(AG_CARD_ID)
        self.assertIsNotNone(record)
        self.assertEqual(record['plasec_identity_id'], IDENTITY_ID)

    def test_get_by_ag_card_id_missing_returns_none(self):
        record = self.local_db.get_by_ag_card_id('nonexistent-id')
        self.assertIsNone(record)

    def test_record_error_creates_placeholder(self):
        """record_error for an unknown identity creates a placeholder error row."""
        self.local_db.record_error(IDENTITY_ID, TOKEN_ID, 'something broke')

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertIsNotNone(record)
        self.assertEqual(record['status'], 'error')
        self.assertIn('something broke', record['sync_error'])
        self.assertEqual(record['retry_count'], 1)

    def test_record_error_increments_retry_count(self):
        self.seed_synced_record()
        self.local_db.record_error(IDENTITY_ID, TOKEN_ID, 'error 1')
        self.local_db.record_error(IDENTITY_ID, TOKEN_ID, 'error 2')

        record = self.local_db.get_by_identity_token(IDENTITY_ID, TOKEN_ID)
        self.assertEqual(record['retry_count'], 2)
        self.assertEqual(record['status'], 'error')

    def test_get_failed_syncs_returns_error_records(self):
        self.seed_synced_record()
        self.local_db.record_error(IDENTITY_ID, TOKEN_ID, 'provisioning failed')

        failed = self.local_db.get_failed_syncs()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['plasec_identity_id'], IDENTITY_ID)

    def test_get_failed_syncs_excludes_active(self):
        self.seed_synced_record()
        failed = self.local_db.get_failed_syncs()
        self.assertEqual(len(failed), 0)

    def test_is_empty_false_after_record(self):
        self.seed_synced_record()
        self.assertFalse(self.local_db.is_empty())


if __name__ == '__main__':
    unittest.main()
