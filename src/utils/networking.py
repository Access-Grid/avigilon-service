"""
Network connectivity utilities for AccessGrid Avigilon Unity Agent
"""

import socket
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def check_internet_connectivity(timeout: float = 3.0) -> bool:
    """Check internet by pinging well-known DNS servers."""
    for host, port in [("8.8.8.8", 53), ("1.1.1.1", 53)]:
        try:
            socket.create_connection((host, port), timeout=timeout)
            return True
        except OSError:
            continue
    logger.warning("No internet connectivity detected")
    return False


def check_host_reachability(
    hostname: str, port: int, timeout: float = 5.0
) -> Tuple[bool, Optional[str]]:
    """Check if hostname:port is reachable. Returns (ok, error_msg)."""
    try:
        socket.create_connection((hostname, port), timeout=timeout)
        return True, None
    except socket.gaierror as e:
        return False, f"DNS failed for {hostname}: {e}"
    except socket.timeout:
        return False, f"Timeout connecting to {hostname}:{port}"
    except OSError as e:
        return False, f"Network error: {e}"


def test_plasec_connectivity(host: str, port: int = 443) -> Tuple[bool, str]:
    """
    Test TCP reachability of the Plasec server.

    Args:
        host: Plasec hostname or IP
        port: HTTPS port (default 443)
    """
    ok, err = check_host_reachability(host, port, timeout=10.0)
    if ok:
        return True, f"Plasec server {host}:{port} is reachable"
    return False, f"Plasec server unreachable: {err}"
