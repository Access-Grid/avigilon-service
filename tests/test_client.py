"""
Unit tests for PlaSecClient — HTTP behaviour, normalization, pagination.
"""

import pytest
import unittest
from unittest.mock import MagicMock

import requests.cookies

from tests.base_test import (
    BaseSyncTest, IDENTITY_ID, TOKEN_ID, CARD_NUMBER, PLASEC_HOST,
    make_mock_response,
)
from tests.fixtures import (
    IDENTITY_LIST_RESPONSE,
    IDENTITY_DETAIL_PERSON,
    TOKEN_LIST_ACTIVE,
    TOKEN_LIST_INACTIVE,
    TOKEN_LIST_EMPTY,
)


@pytest.mark.unit
class TestNormalization(unittest.TestCase):
    """Response normalization methods."""

    def setUp(self):
        from src.api.client import PlaSecClient
        self.client = PlaSecClient(
            host=PLASEC_HOST,
            username='admin',
            password='test',
            verify_ssl=False,
        )

    def test_identity_from_list_parses_plasec_name(self):
        """List endpoint: parse 'Lastname, Firstname' from plasecName."""
        raw = {
            'cn': IDENTITY_ID,
            'plasecName': 'Person, Test',
            'plasecIdstatus': 'Active',
        }
        result = self.client._normalize_identity(raw)

        self.assertEqual(result['id'], IDENTITY_ID)
        self.assertEqual(result['first_name'], 'Test')
        self.assertEqual(result['last_name'], 'Person')
        self.assertEqual(result['full_name'], 'Test Person')
        self.assertEqual(result['status'], '1')

    def test_identity_from_detail_uses_separate_name_fields(self):
        """Detail endpoint: prefer plasecFname/plasecLname over plasecName."""
        raw = IDENTITY_DETAIL_PERSON['data']
        result = self.client._normalize_identity(raw)

        self.assertEqual(result['id'], IDENTITY_ID)
        self.assertEqual(result['first_name'], 'Test')
        self.assertEqual(result['last_name'], 'Person')
        self.assertEqual(result['full_name'], 'Test Person')
        self.assertEqual(result['email'], 'test.person@example.com')
        self.assertEqual(result['phone'], '555-1234')
        self.assertEqual(result['status'], '1')

    def test_identity_status_string_normalization(self):
        c = self.client
        self.assertEqual(c._normalize_identity_status('Active'), '1')
        self.assertEqual(c._normalize_identity_status('active'), '1')
        self.assertEqual(c._normalize_identity_status('Inactive'), '2')
        self.assertEqual(c._normalize_identity_status('inactive'), '2')
        self.assertEqual(c._normalize_identity_status('1'), '1')
        self.assertEqual(c._normalize_identity_status('2'), '2')
        self.assertEqual(c._normalize_identity_status('3'), '3')
        self.assertEqual(c._normalize_identity_status('4'), '4')
        # Unknown → default '1'
        self.assertEqual(c._normalize_identity_status(''), '1')

    def test_token_normalization(self):
        """cn → id, plasecInternalnumber → internal_number."""
        raw = TOKEN_LIST_ACTIVE['data'][0]
        result = self.client._normalize_token(raw, IDENTITY_ID)

        self.assertEqual(result['id'], TOKEN_ID)
        self.assertEqual(result['identity_id'], IDENTITY_ID)
        self.assertEqual(result['internal_number'], CARD_NUMBER)
        self.assertEqual(result['status'], '1')

    def test_token_inactive_normalization(self):
        raw = TOKEN_LIST_INACTIVE['data'][0]
        result = self.client._normalize_token(raw, IDENTITY_ID)

        self.assertEqual(result['id'], TOKEN_ID)
        self.assertEqual(result['status'], '2')


@pytest.mark.unit
class TestClientRequests(BaseSyncTest):
    """HTTP request methods using mocked session."""

    def test_get_all_identities_returns_all_entries(self):
        """Single-page response returns all identities."""
        self.configure_http({
            '/identities.json': make_mock_response(200, IDENTITY_LIST_RESPONSE),
        })

        identities = self.plasec_client.get_all_identities()

        # IDENTITY_LIST_RESPONSE has 3 entries (0, e01c265bdfc24d70, 6961cb7d2c664248)
        self.assertEqual(len(identities), 3)
        ids = {i['id'] for i in identities}
        self.assertIn(IDENTITY_ID, ids)

    def test_get_all_identities_paginates(self):
        """Requests a second page when recordsFiltered > 100."""
        page1 = {
            'data': [
                {'cn': f'{i:016x}', 'plasecName': f'Z, Person{i}',
                 'plasecIdstatus': 'Active'}
                for i in range(100)
            ],
            'meta': {'recordsTotal': 150, 'recordsFiltered': 150},
            'success': True,
        }
        page2 = {
            'data': [
                {'cn': f'{i:016x}', 'plasecName': f'Z, Person{i}',
                 'plasecIdstatus': 'Active'}
                for i in range(100, 150)
            ],
            'meta': {'recordsTotal': 150, 'recordsFiltered': 150},
            'success': True,
        }
        call_count = [0]

        def handler(method, url, **kwargs):
            call_count[0] += 1
            page = kwargs.get('params', {}).get('page', 1)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = page1 if page == 1 else page2
            resp.headers = {}
            resp.url = f'https://{PLASEC_HOST}/identities.json'
            resp.cookies = requests.cookies.RequestsCookieJar()
            return resp

        self.mock_session.request.side_effect = handler

        identities = self.plasec_client.get_all_identities()

        self.assertEqual(len(identities), 150)
        self.assertEqual(call_count[0], 2)

    def test_get_identity_normalizes_detail(self):
        self.configure_http({
            f'/identities/{IDENTITY_ID}.json': make_mock_response(200, IDENTITY_DETAIL_PERSON),
        })

        identity = self.plasec_client.get_identity(IDENTITY_ID)

        self.assertIsNotNone(identity)
        self.assertEqual(identity['id'], IDENTITY_ID)
        self.assertEqual(identity['email'], 'test.person@example.com')
        self.assertEqual(identity['phone'], '555-1234')

    def test_get_identity_returns_none_on_error(self):
        self.configure_http({
            f'/identities/{IDENTITY_ID}.json': make_mock_response(404),
        })

        identity = self.plasec_client.get_identity(IDENTITY_ID)

        self.assertIsNone(identity)

    def test_get_identity_tokens_returns_normalized_list(self):
        self.configure_http({
            f'/identities/{IDENTITY_ID}/tokens.json': make_mock_response(200, TOKEN_LIST_ACTIVE),
        })

        tokens = self.plasec_client.get_identity_tokens(IDENTITY_ID)

        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0]['id'], TOKEN_ID)
        self.assertEqual(tokens[0]['internal_number'], CARD_NUMBER)

    def test_get_identity_tokens_empty(self):
        self.configure_http({
            f'/identities/{IDENTITY_ID}/tokens.json': make_mock_response(200, TOKEN_LIST_EMPTY),
        })

        tokens = self.plasec_client.get_identity_tokens(IDENTITY_ID)

        self.assertEqual(tokens, [])


@pytest.mark.unit
class TestSessionExpiry(unittest.TestCase):
    """Session expiry detection logic."""

    def setUp(self):
        from src.api.client import PlaSecClient
        self.client = PlaSecClient(
            host=PLASEC_HOST, username='admin', password='test', verify_ssl=False
        )

    def test_302_to_sessions_is_expired(self):
        resp = make_mock_response(302)
        resp.headers = {'Location': f'https://{PLASEC_HOST}/sessions'}
        self.assertTrue(self.client._is_session_expired(resp, '/identities.json'))

    def test_302_to_other_path_is_not_expired(self):
        resp = make_mock_response(302)
        resp.headers = {'Location': f'https://{PLASEC_HOST}/identities'}
        self.assertFalse(self.client._is_session_expired(resp, '/identities'))

    def test_200_with_sessions_in_url_is_expired(self):
        resp = make_mock_response(200)
        resp.url = f'https://{PLASEC_HOST}/sessions'
        self.assertTrue(self.client._is_session_expired(resp, '/identities.json'))

    def test_200_with_normal_url_not_expired(self):
        resp = make_mock_response(200)
        resp.url = f'https://{PLASEC_HOST}/identities.json'
        self.assertFalse(self.client._is_session_expired(resp, '/identities.json'))


@pytest.mark.unit
class TestLogin(unittest.TestCase):
    """Login flow tests."""

    def setUp(self):
        from src.api.client import PlaSecClient
        self.client = PlaSecClient(
            host=PLASEC_HOST, username='admin', password='test', verify_ssl=False
        )
        self.mock_session = MagicMock()
        self.client.session = self.mock_session

    def test_login_success_sets_logged_in(self):
        resp = MagicMock()
        resp.status_code = 302
        self.mock_session.post.return_value = resp

        jar = requests.cookies.RequestsCookieJar()
        jar.set('_session_id', 'test-session-id')
        jar.set('XSRF-TOKEN', 'test-csrf-token')
        self.mock_session.cookies = jar

        result = self.client.login()

        self.assertTrue(result)
        self.assertTrue(self.client._logged_in)

    def test_login_failure_no_session_cookie(self):
        resp = MagicMock()
        resp.status_code = 200
        self.mock_session.post.return_value = resp
        self.mock_session.cookies = requests.cookies.RequestsCookieJar()

        result = self.client.login()

        self.assertFalse(result)
        self.assertFalse(self.client._logged_in)

    def test_csrf_token_from_cookie(self):
        jar = requests.cookies.RequestsCookieJar()
        jar.set('XSRF-TOKEN', 'my-csrf-token')
        self.mock_session.cookies = jar
        self.client.session = self.mock_session

        self.assertEqual(self.client.csrf_token, 'my-csrf-token')


if __name__ == '__main__':
    unittest.main()
