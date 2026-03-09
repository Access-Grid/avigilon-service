"""
Base test class for AccessGrid Avigilon Unity Agent tests.

Provides:
  - PlaSecClient with a mocked requests.Session (no live server needed)
  - In-memory SQLite LocalDB
  - Mocked AccessGrid client
  - HTTP route helper for configuring per-test mock responses
"""

import sqlite3
import sys
import os
import unittest
from unittest.mock import MagicMock

import requests.cookies

# Make src importable when running from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.api.client import PlaSecClient
from src.sync.local_db import LocalDB
from src.sync.strategies import SyncStrategies

# Stable IDs used across all scenario tests (taken from live captures)
IDENTITY_ID       = '6961cb7d2c664248'   # "Person, Test"
TOKEN_ID          = '54a67bf3a2944214'
IDENTITY_ID_2     = 'e01c265bdfc24d70'   # "Cooper, Jim"
TOKEN_ID_2        = '4afa49c39cb44495'
CARD_NUMBER       = '1234'
AG_CARD_ID        = 'ag-card-abc123'
TEMPLATE_ID       = 'test-template-id'
PLASEC_HOST       = '192.0.2.1'   # RFC 5737 TEST-NET — never a real host


def make_mock_response(status_code=200, json_data=None, headers=None, url=None):
    """Build a MagicMock that looks like a requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.url = url or f'https://{PLASEC_HOST}/'
    resp.cookies = requests.cookies.RequestsCookieJar()
    return resp


class BaseSyncTest(unittest.TestCase):
    """
    Base class for all sync scenario tests.

    setUp() wires up:
      - self.plasec_client   — PlaSecClient with mocked HTTP session
      - self.mock_session    — the MagicMock session; configure .request.side_effect
      - self.local_db        — in-memory SQLite LocalDB
      - self.ag_client       — MagicMock AccessGrid client
      - self.strategies      — SyncStrategies using all of the above
    """

    def setUp(self):
        # --- Plasec client with mocked HTTP session ---
        self.plasec_client = PlaSecClient(
            host=PLASEC_HOST,
            username='admin',
            password='test_password',
            verify_ssl=False,
        )
        # Bypass login; inject mocked session
        self.plasec_client._logged_in = True
        self.mock_session = MagicMock()
        self.mock_session.cookies = requests.cookies.RequestsCookieJar()
        self.mock_session.cookies.set('XSRF-TOKEN', 'test-csrf-token')
        self.mock_session.cookies.set('_session_id', 'test-session-id')
        self.plasec_client.session = self.mock_session

        # --- In-memory SQLite LocalDB ---
        self.local_db = LocalDB(':memory:')
        self.local_db._conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.local_db._conn.row_factory = sqlite3.Row
        self.local_db.ensure_table()

        # --- Mock AccessGrid client ---
        self.ag_client = MagicMock()
        self.ag_client.access_cards.create.return_value = {'id': AG_CARD_ID}

        # --- SyncStrategies ---
        self.strategies = SyncStrategies(
            plasec_client=self.plasec_client,
            local_db=self.local_db,
            ag_client=self.ag_client,
            template_id=TEMPLATE_ID,
        )

    def tearDown(self):
        if self.local_db._conn:
            self.local_db._conn.close()

    # ------------------------------------------------------------------
    # HTTP mock helpers
    # ------------------------------------------------------------------

    def configure_http(self, routes: dict):
        """
        Wire self.mock_session.request to dispatch based on URL substring.

        routes: { url_fragment: mock_response, ... }
        Matched in insertion order; first match wins.
        """
        def handler(method, url, **kwargs):
            for fragment, response in routes.items():
                if fragment in url:
                    return response
            raise AssertionError(f"Unexpected request: {method} {url}")

        self.mock_session.request.side_effect = handler

    def seed_synced_record(
        self,
        identity_id=IDENTITY_ID,
        token_id=TOKEN_ID,
        ag_card_id=AG_CARD_ID,
        card_number=CARD_NUMBER,
        token_status='1',
    ):
        """Insert a pre-existing sync record into the local DB."""
        self.local_db.record_sync(
            identity_id=identity_id,
            token_id=token_id,
            ag_card_id=ag_card_id,
            card_number=card_number,
            full_name='Test Person',
            email='test.person@example.com',
            phone='555-1234',
            token_status=token_status,
        )

    def get_db_record(self, identity_id=IDENTITY_ID, token_id=TOKEN_ID):
        return self.local_db.get_by_identity_token(identity_id, token_id)
