"""
Sync algorithms for AccessGrid Avigilon Unity Agent.

All 6 phases share a single per-cycle snapshot so that Plasec is only
queried once per cycle instead of once per phase.

Snapshot contents (built at the start of each cycle):
  identity_map    — all live identities (from paginated list endpoint)
  token_map       — tokens per active identity (from tokens.json)
  active_pairs    — set of (identity_id, token_id) for quick membership tests
  detail_cache    — full identity detail (lazily fetched on first access)

Status translation:
  Plasec plasecTokenstatus 1  → AccessGrid 'active'
  Plasec plasecTokenstatus 2+ → AccessGrid 'suspended'
  AccessGrid 'deleted'        → remove token tracking from local DB
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..api.client import PlaSecClient
from ..sync.local_db import LocalDB
from ..constants import (
    AG_TO_PLASEC_STATUS,
    PLASEC_TO_AG_STATUS,
    PLASEC_TOKEN_STATUS_ACTIVE,
    PLASEC_TOKEN_STATUS_INACTIVE,
    MAX_RETRY_COUNT,
)

try:
    from accessgrid import AccessGrid, AccessGridError
except ImportError:
    class AccessGrid:
        def __init__(self, *args, **kwargs): pass
    class AccessGridError(Exception): pass

logger = logging.getLogger(__name__)


@dataclass
class _CycleSnapshot:
    """Plasec data fetched once at the start of each sync cycle."""
    identity_map: Dict[str, Dict] = field(default_factory=dict)
    token_map: Dict[str, List[Dict]] = field(default_factory=dict)
    active_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    detail_cache: Dict[str, Optional[Dict]] = field(default_factory=dict)


class SyncStrategies:
    """Sync logic between Plasec (source) and AccessGrid (destination)."""

    # Standard Wiegand format: {card_len_bits: (fc_bits, cn_bits)}
    _WIEGAND_FORMATS: Dict[int, tuple] = {
        26: (8,  16),
        34: (16, 16),
        35: (12, 20),
        36: (8,  26),
        37: (16, 19),
    }

    def __init__(
        self,
        plasec_client: PlaSecClient,
        local_db: LocalDB,
        ag_client: AccessGrid,
        template_id: str,
        template_protocol: str = '',
        default_facility_code: str = '',
        card_len: str = '',
        max_bits: str = '',
    ):
        self.plasec                 = plasec_client
        self.db                     = local_db
        self.ag                     = ag_client
        self.template_id            = template_id
        self.template_protocol      = template_protocol.lower() if template_protocol else ''
        self.default_facility_code  = default_facility_code
        self.card_len               = card_len
        self.max_bits               = max_bits

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_cycle(self) -> Dict[str, int]:
        """
        Execute all 6 sync phases, sharing a single Plasec data snapshot.

        Returns per-phase metrics dict.
        """
        snap = self._build_snapshot()

        new        = self._phase1_new_identities(snap)
        status     = self._phase2_status_changes(snap)
        deletions  = self._phase3_deletions(snap)
        ag_to_p    = self._phase4_ag_to_plasec(snap)
        retried    = self._phase5_retries(snap)
        fields     = self._phase6_field_changes(snap)

        return {
            'new':            new,
            'status_changes': status,
            'deleted':        deletions['deleted'],
            'orphaned':       deletions['orphaned'],
            'ag_to_plasec':   ag_to_p,
            'retried':        retried,
            'field_changes':  fields,
        }

    # ------------------------------------------------------------------
    # Snapshot construction
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> _CycleSnapshot:
        """
        Fetch all identities and their tokens from Plasec in one pass.

        Tokens are only fetched for active identities — inactive identities
        cannot have active tokens worth syncing.
        """
        snap = _CycleSnapshot()

        for identity in self.plasec.get_all_identities():
            iid = identity.get('id')
            if iid:
                snap.identity_map[iid] = identity

        for iid, identity in snap.identity_map.items():
            if identity.get('status') != '1':
                continue
            tokens = self.plasec.get_identity_tokens(iid)
            snap.token_map[iid] = tokens
            for t in tokens:
                tid = t.get('id')
                if tid:
                    snap.active_pairs.add((iid, tid))

        logger.debug(
            f"Snapshot: {len(snap.identity_map)} identities, "
            f"{sum(len(v) for v in snap.token_map.values())} tokens"
        )
        return snap

    def _get_detail(self, snap: _CycleSnapshot, identity_id: str) -> Optional[Dict]:
        """Lazily fetch full identity detail (email/phone), caching the result."""
        if identity_id not in snap.detail_cache:
            snap.detail_cache[identity_id] = self.plasec.get_identity(identity_id)
        return snap.detail_cache[identity_id]

    # ------------------------------------------------------------------
    # Phase 1: New Plasec identities/tokens → AccessGrid provisioning
    # ------------------------------------------------------------------

    def _phase1_new_identities(self, snap: _CycleSnapshot) -> int:
        already_synced = self.db.get_synced_identity_token_pairs()
        provisioned = 0

        for iid, tokens in snap.token_map.items():
            for token in tokens:
                tid = token.get('id', '')
                if not tid:
                    continue
                if token.get('status') != PLASEC_TOKEN_STATUS_ACTIVE:
                    continue
                if (iid, tid) in already_synced:
                    continue

                # Full detail needed for email/phone — fetch lazily, shared across tokens
                full_identity = self._get_detail(snap, iid) or snap.identity_map[iid]
                item = self._build_sync_item(full_identity, token)

                if self._provision(item):
                    provisioned += 1

        return provisioned

    def _provision(self, item: Dict) -> bool:
        """Provision an AccessGrid mobile credential for a Plasec identity+token."""
        iid         = item['identity_id']
        tid         = item['token_id']
        card_number = item.get('card_number', '')
        full_name   = item.get('full_name', '')
        email       = item.get('identity', {}).get('email', '')
        phone       = item.get('identity', {}).get('phone', '')

        is_seos = self.template_protocol == 'seos'

        if not full_name:
            logger.warning(f"Skipping identity {iid} token {tid}: no name")
            return False
        if not email and not phone:
            logger.warning(f"Skipping identity {iid} token {tid}: no email or phone")
            return False
        if not is_seos and not card_number:
            logger.warning(f"Skipping identity {iid} token {tid}: no card number")
            return False

        try:
            provision_kwargs: Dict = dict(
                card_template_id=self.template_id,
                employee_id=iid,
                full_name=full_name,
                email=email,
                phone_number=phone,
                start_date=item.get('activate_date') or None,
                expiration_date=item.get('deactivate_date') or None,
            )

            if not is_seos:
                logger.debug(
                    f"Non-seos provision for {iid}/{tid}: "
                    f"facility_code={self.default_facility_code!r}, "
                    f"card_number={card_number!r}, "
                    f"card_len={self.card_len!r}, "
                    f"max_bits={self.max_bits!r}"
                )
                try:
                    file_data = self._build_file_data(
                        facility_code=int(self.default_facility_code or 0),
                        card_number=int(card_number),
                        card_len=int(self.card_len or 0),
                        max_bits=int(self.max_bits or 0),
                    )
                    logger.debug(f"_build_file_data returned: {file_data!r}")
                    if file_data:
                        provision_kwargs['file_data'] = file_data
                    else:
                        logger.debug("file_data is empty — not including in provision call")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not build file_data for {iid}/{tid}: {e}")
            else:
                logger.debug(f"Seos provision for {iid}/{tid} — skipping file_data")

            logger.debug(f"provision_kwargs: {provision_kwargs}")
            result = self.ag.access_cards.provision(**provision_kwargs)
            ag_card_id = result.id
            if not ag_card_id:
                raise ValueError(f"AccessGrid returned no card ID: {result}")

            self.db.record_sync(
                identity_id=iid,
                token_id=tid,
                ag_card_id=ag_card_id,
                card_number=card_number,
                full_name=full_name,
                email=email,
                phone=phone,
                token_status=item.get('token', {}).get('status', '1'),
            )
            logger.info(f"Synced {full_name} → AG card {ag_card_id}")
            return True

        except AccessGridError as e:
            logger.error(f"AccessGrid error for identity {iid}: {e}")
            self.db.record_error(iid, tid, str(e))
            return False
        except Exception as e:
            logger.error(f"Unexpected error provisioning identity {iid}: {e}", exc_info=True)
            self.db.record_error(iid, tid, str(e))
            return False

    # ------------------------------------------------------------------
    # Phase 2: Plasec token status changes → AccessGrid
    # ------------------------------------------------------------------

    def _phase2_status_changes(self, snap: _CycleSnapshot) -> int:
        updated = 0

        for record in self.db.get_active_synced():
            iid        = record['plasec_identity_id']
            tid        = record['plasec_token_id']
            ag_card_id = record['accessgrid_card_id']

            tokens = snap.token_map.get(iid, [])
            token  = next((t for t in tokens if t['id'] == tid), None)
            if token is None:
                continue  # deletion handled in Phase 3

            current   = token.get('status', '1')
            last_seen = record.get('last_synced_token_status', '1')
            if current == last_seen:
                continue

            ag_action = PLASEC_TO_AG_STATUS.get(current)
            if not ag_action:
                logger.warning(f"Unknown Plasec token status {current!r} for token {tid}")
                continue

            logger.info(
                f"Status change: identity {iid} token {tid} "
                f"Plasec {last_seen}→{current}, AG action: {ag_action}"
            )
            try:
                self._apply_ag_action(ag_card_id, ag_action)
                self.db.update_token_status_seen(iid, tid, current)
                updated += 1
            except Exception as e:
                logger.error(f"Failed to apply AG action for token {tid}: {e}")

        return updated

    # ------------------------------------------------------------------
    # Phase 3: Deleted identities/tokens → terminate AG cards
    # ------------------------------------------------------------------

    def _phase3_deletions(self, snap: _CycleSnapshot) -> Dict:
        metrics = {'deleted': 0, 'orphaned': 0}

        for record in self.db.get_active_synced():
            iid        = record['plasec_identity_id']
            tid        = record['plasec_token_id']
            ag_card_id = record['accessgrid_card_id']

            if iid not in snap.identity_map:
                logger.info(
                    f"Identity {iid} gone from Plasec — terminating AG card {ag_card_id}"
                )
                self._delete_ag_card(ag_card_id)
                self.db.mark_deleted(iid, tid)
                metrics['deleted'] += 1
                continue

            token_ids = {t['id'] for t in snap.token_map.get(iid, [])}
            if tid not in token_ids:
                logger.info(
                    f"Token {tid} gone from identity {iid} — terminating AG card {ag_card_id}"
                )
                self._delete_ag_card(ag_card_id)
                self.db.mark_deleted(iid, tid)
                metrics['orphaned'] += 1

        return metrics

    # ------------------------------------------------------------------
    # Phase 4: AccessGrid status changes → Plasec
    # ------------------------------------------------------------------

    def _phase4_ag_to_plasec(self, snap: _CycleSnapshot) -> int:
        synced = self.db.get_active_synced()
        if not synced:
            return 0

        try:
            ag_cards = self.ag.access_cards.list(template_id=self.template_id)
        except Exception as e:
            logger.error(f"Failed to list AG cards: {e}")
            return 0

        ag_card_map = {c.id: c for c in ag_cards if c.id}
        updated = 0

        for record in synced:
            ag_card_id = record['accessgrid_card_id']
            iid        = record['plasec_identity_id']
            tid        = record['plasec_token_id']

            ag_card = ag_card_map.get(ag_card_id)
            if not ag_card:
                continue

            ag_state             = (getattr(ag_card, 'state', 'active') or 'active').lower()
            desired_plasec       = AG_TO_PLASEC_STATUS.get(ag_state)
            current_plasec       = record.get('last_synced_token_status', '1')

            if not desired_plasec or desired_plasec == current_plasec:
                continue

            logger.info(
                f"AG card {ag_card_id} is {ag_state!r} — "
                f"updating Plasec token {tid} to {desired_plasec}"
            )
            current_token = next(
                (t for t in snap.token_map.get(iid, []) if t['id'] == tid), None
            )
            if self.plasec.update_token_status(iid, tid, desired_plasec, current_token):
                self.db.update_token_status_seen(iid, tid, desired_plasec)
                self.db.update_status(iid, tid, ag_state)
                updated += 1

        return updated

    # ------------------------------------------------------------------
    # Phase 5: Retry failed provisioning
    # ------------------------------------------------------------------

    def _phase5_retries(self, snap: _CycleSnapshot) -> int:
        retried = 0

        for record in self.db.get_failed_syncs():
            iid = record['plasec_identity_id']
            tid = record['plasec_token_id']

            logger.info(
                f"Retrying failed sync: identity={iid} token={tid} "
                f"(attempt {record['retry_count'] + 1}/{MAX_RETRY_COUNT})"
            )

            if iid not in snap.identity_map:
                logger.warning(f"Identity {iid} no longer exists — skipping retry")
                self.db.mark_deleted(iid, tid)
                continue

            token = next(
                (t for t in snap.token_map.get(iid, []) if t['id'] == tid), None
            )
            if not token:
                logger.warning(f"Token {tid} no longer exists — skipping retry")
                self.db.mark_deleted(iid, tid)
                continue

            full_identity = self._get_detail(snap, iid) or snap.identity_map[iid]
            item = self._build_sync_item(full_identity, token)
            if self._provision(item):
                retried += 1

        return retried

    # ------------------------------------------------------------------
    # Phase 6: Field changes (name, email, phone) → AccessGrid
    # ------------------------------------------------------------------

    def _phase6_field_changes(self, snap: _CycleSnapshot) -> int:
        changed = 0

        for record in self.db.get_active_synced():
            iid        = record['plasec_identity_id']
            tid        = record['plasec_token_id']
            ag_card_id = record['accessgrid_card_id']

            try:
                identity = self._get_detail(snap, iid)
                if not identity:
                    continue

                cur_name  = identity.get('full_name', '')
                cur_email = identity.get('email', '')
                cur_phone = identity.get('phone', '')

                if (cur_name  == record.get('full_name', '') and
                        cur_email == record.get('last_synced_email', '') and
                        cur_phone == record.get('last_synced_phone', '')):
                    continue

                logger.info(
                    f"Field change for identity {iid} — updating AG card {ag_card_id}"
                )
                update_params = {}
                if cur_name  != record.get('full_name', ''):
                    update_params['full_name'] = cur_name
                if cur_email != record.get('last_synced_email', ''):
                    update_params['email'] = cur_email
                if cur_phone != record.get('last_synced_phone', ''):
                    update_params['phone_number'] = cur_phone

                self.ag.access_cards.update(card_id=ag_card_id, **update_params)
                self.db.update_field_snapshot(iid, tid, cur_name, cur_email, cur_phone)
                changed += 1

            except Exception as e:
                logger.error(f"Error syncing field changes for identity {iid}: {e}")

        return changed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_sync_item(self, identity: Dict, token: Dict) -> Dict:
        iid       = identity.get('id', '')
        tid       = token.get('id', '')
        first     = identity.get('first_name', '')
        last      = identity.get('last_name', '')
        full_name = identity.get('full_name') or f"{first} {last}".strip()
        card_num  = token.get('internal_number', '') or token.get('embossed_number', '')

        return {
            'identity_id':    iid,
            'token_id':       tid,
            'identity':       identity,
            'token':          token,
            'card_number':    card_num,
            'full_name':      full_name,
            'activate_date':  token.get('activate_date', ''),
            'deactivate_date': token.get('deactivate_date', ''),
        }

    @staticmethod
    def _build_file_data(facility_code: int, card_number: int, card_len: int, max_bits: int) -> str:
        """
        Encode a Wiegand credential as a hex string for DESFire/SmartTap provisioning.

        Layout: even_parity(1) | facility_code(fc_bits) | card_number(cn_bits) | odd_parity(1)
        Result is zero-padded to ceil(max_bits/8) bytes, max 32 bytes, big-endian.
        """
        if card_len < 4:
            return ''

        data_bits = card_len - 2  # strip 2 parity bits
        fc_bits, cn_bits = SyncStrategies._WIEGAND_FORMATS.get(
            card_len, (max(8, data_bits // 4), 0)
        )
        if not cn_bits:
            cn_bits = data_bits - fc_bits

        fc = facility_code & ((1 << fc_bits) - 1)
        cn = card_number   & ((1 << cn_bits) - 1)

        # Split data bits into upper / lower halves for parity computation
        upper_half = data_bits // 2
        lower_half = data_bits - upper_half

        if fc_bits >= upper_half:
            upper_data = fc >> (fc_bits - upper_half)
        else:
            cn_upper = upper_half - fc_bits
            upper_data = (fc << cn_upper) | (cn >> (cn_bits - cn_upper))

        lower_data = cn & ((1 << lower_half) - 1)

        # Even parity: total 1s (parity bit + upper_data) must be even
        even_p = bin(upper_data).count('1') % 2
        # Odd parity: total 1s (parity bit + lower_data) must be odd
        odd_p  = 1 - (bin(lower_data).count('1') % 2)

        packed = (even_p << (card_len - 1)) | (fc << (cn_bits + 1)) | (cn << 1) | odd_p

        num_bytes   = (card_len  + 7) // 8
        total_bytes = min(32, max(num_bytes, (max_bits + 7) // 8))
        card_bytes  = packed.to_bytes(num_bytes, byteorder='big')
        padded      = card_bytes + b'\x00' * max(0, total_bytes - num_bytes)
        return padded.hex()

    def _apply_ag_action(self, ag_card_id: str, action: str):
        if action == 'suspended':
            self.ag.access_cards.suspend(card_id=ag_card_id)
        elif action == 'active':
            self.ag.access_cards.resume(card_id=ag_card_id)
        elif action in ('deleted', 'terminated'):
            self._delete_ag_card(ag_card_id)

    def _delete_ag_card(self, ag_card_id: str):
        try:
            self.ag.access_cards.delete(card_id=ag_card_id)
            logger.info(f"Deleted AG card {ag_card_id}")
        except AccessGridError as e:
            if 'not found' in str(e).lower() or '404' in str(e):
                logger.debug(f"AG card {ag_card_id} already gone: {e}")
            else:
                raise
