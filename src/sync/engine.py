"""
Core synchronization engine for AccessGrid Avigilon Unity Agent.

Runs a 6-phase sync loop in a background thread:
  1. New Plasec identities → AccessGrid provisioning
  2. Plasec token status changes → AccessGrid
  3. Deleted identities/tokens → AccessGrid termination
  4. AccessGrid status changes → Plasec token updates
  5. Retry previously failed syncs
  6. Field changes (name/email/phone) → AccessGrid
"""

import threading
import time
import logging
from datetime import datetime
from typing import Dict, Optional

import sentry_sdk

from ..api.client import PlaSecClient
from ..sync.local_db import LocalDB
from ..sync.strategies import SyncStrategies
from ..constants import MIN_SYNC_INTERVAL, SYNC_INTERVAL_MULTIPLIER, ERROR_BACKOFF_SECONDS

try:
    from accessgrid import AccessGrid, AccessGridError
except ImportError:
    class AccessGrid:
        def __init__(self, *args, **kwargs): pass
    class AccessGridError(Exception): pass

logger = logging.getLogger(__name__)


class SyncEngine:
    """Orchestrates the periodic sync between Plasec and AccessGrid."""

    def __init__(
        self,
        plasec_client: PlaSecClient,
        local_db: LocalDB,
        ag_client: AccessGrid,
        config: dict,
    ):
        self.plasec   = plasec_client
        self.db       = local_db
        self.ag       = ag_client
        self.config   = config

        self.strategies = SyncStrategies(
            plasec_client=plasec_client,
            local_db=local_db,
            ag_client=ag_client,
            template_id=config['accessgrid']['template_id'],
            facility_code=config.get('plasec', {}).get('facility_code', ''),
        )

        self.running        = False
        self.error_count    = 0
        self.last_sync_time: Optional[datetime] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_interval = MIN_SYNC_INTERVAL

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self):
        """Start the sync loop in a daemon background thread."""
        if not self.running:
            self._sync_thread = threading.Thread(
                target=self._sync_loop, daemon=True, name="AvigilonSyncThread"
            )
            self._sync_thread.start()
            logger.info("Sync engine started")

    def stop(self):
        """Signal the sync loop to stop and wait for the thread."""
        logger.info("Stopping sync engine...")
        self.running = False
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=10.0)
        logger.info("Sync engine stopped")

    def get_status(self) -> Dict:
        return {
            'running':        self.running,
            'last_sync_time': self.last_sync_time,
            'error_count':    self.error_count,
            'sync_interval':  self._sync_interval,
        }

    def force_sync(self) -> bool:
        """Execute one full sync cycle immediately (called from GUI)."""
        if not self.running:
            logger.warning("Cannot force sync — engine not running")
            return False
        try:
            self._run_one_cycle()
            return True
        except Exception as e:
            logger.error(f"Force sync failed: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal sync loop
    # ------------------------------------------------------------------

    def _resolve_template_config(self):
        """
        Fetch AG template protocol and Plasec card format details.
        Called once before the sync loop starts; results stored on self.strategies.
        """
        template_id = self.config['accessgrid']['template_id']

        # --- AG template protocol (seos / desfire / smart_tap / ...) ---
        try:
            tmpl = self.ag.console.read_template(template_id=template_id)
            logger.debug(f"AG template response: {tmpl}")
            logger.debug(f"AG template attrs: protocol={getattr(tmpl, 'protocol', None)}")
            protocol = getattr(tmpl, 'protocol', '') or ''
            self.strategies.template_protocol = protocol.lower()
            logger.info(f"Template {template_id} protocol: {protocol!r}")
        except Exception as e:
            logger.warning(f"Could not fetch AG template protocol: {e}")
            logger.debug(f"template_protocol remains: {self.strategies.template_protocol!r}")

        logger.info(f"Using facility_code from config: {self.strategies.facility_code!r}")

    def _sync_loop(self):
        self.running = True
        logger.info(
            f"Sync loop starting — template={self.config['accessgrid']['template_id']}"
        )

        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("template_id", self.config['accessgrid']['template_id'])
            scope.set_tag("plasec_host",  self.config['plasec']['host'])

        self._resolve_template_config()

        while self.running:
            try:
                self._run_one_cycle()
                self.last_sync_time = datetime.now()
                self.error_count    = 0
                logger.info(
                    f"Sync cycle complete at {self.last_sync_time.strftime('%H:%M:%S')} — "
                    f"next in {self._sync_interval:.0f}s"
                )
                time.sleep(self._sync_interval)

            except Exception as e:
                self.error_count += 1
                logger.error(f"Sync loop error #{self.error_count}: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)

                if self.error_count > 10:
                    logger.error("Too many consecutive errors — stopping sync engine")
                    self.running = False
                else:
                    logger.warning(f"Backing off for {ERROR_BACKOFF_SECONDS}s")
                    time.sleep(ERROR_BACKOFF_SECONDS)

    def _run_one_cycle(self):
        """
        Execute all 6 sync phases.

        A single Plasec data snapshot is built at the start of the cycle and
        shared across all phases, so the server is only queried once for the
        full identity/token list regardless of how many phases need that data.
        """
        m = self.strategies.run_cycle()

        if m['new']:
            logger.info(f"Phase 1: Provisioned {m['new']} new card(s)")
        if m['status_changes']:
            logger.info(f"Phase 2: Pushed {m['status_changes']} status change(s) to AG")
        total_deleted = m['deleted'] + m['orphaned']
        if total_deleted:
            logger.info(
                f"Phase 3: Terminated {total_deleted} card(s) "
                f"(identity gone: {m['deleted']}, token orphaned: {m['orphaned']})"
            )
        if m['ag_to_plasec']:
            logger.info(f"Phase 4: Updated {m['ag_to_plasec']} Plasec token(s) from AG")
        if m['retried']:
            logger.info(f"Phase 5: Retried {m['retried']} failed sync(s)")
        if m['field_changes']:
            logger.info(f"Phase 6: Updated {m['field_changes']} card(s) for field changes")
