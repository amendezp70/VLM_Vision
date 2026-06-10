# vlm_vision/local_agent/traceability/catalyst_auth.py
"""
CatalystAuth -- hands out a valid Zoho Catalyst access token, refreshing it
automatically when it expires.

Zoho access tokens last ~1 hour. Rather than refresh on every call, this holds
the long-lived refresh token (+ client id/secret) and caches the current
access token, only calling Zoho's token endpoint when the cached one is stale.

All secrets come from TraceabilityConfig (i.e. from .env) -- nothing hardcoded.

Usage:
    auth = CatalystAuth.from_config(cfg)
    token = auth.get_token()        # always valid; refreshes itself as needed
"""
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Refresh a bit early so a token never expires mid-request.
_EXPIRY_SAFETY_SEC = 120


class CatalystAuthError(Exception):
    """Raised when a token cannot be obtained (bad credentials, network, etc.)."""


class CatalystAuth:
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        accounts_url: str = "https://accounts.zoho.com",
        request_timeout: float = 15.0,
    ):
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._accounts_url = accounts_url.rstrip("/")
        self._timeout = request_timeout
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0  # unix time when the cached token dies

    @classmethod
    def from_config(cls, cfg) -> "CatalystAuth":
        return cls(
            refresh_token=cfg.catalyst_refresh_token,
            client_id=cfg.catalyst_client_id,
            client_secret=cfg.catalyst_client_secret,
            accounts_url=cfg.catalyst_accounts_url,
        )

    def has_credentials(self) -> bool:
        return bool(self._refresh_token and self._client_id and self._client_secret)

    def _is_token_valid(self) -> bool:
        return bool(self._access_token) and time.time() < (self._expires_at - _EXPIRY_SAFETY_SEC)

    def get_token(self, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing if needed. Raises
        CatalystAuthError if one cannot be obtained."""
        if not force_refresh and self._is_token_valid():
            return self._access_token
        return self._refresh()

    def _refresh(self) -> str:
        if not self.has_credentials():
            raise CatalystAuthError("Missing Catalyst credentials (check .env)")
        url = f"{self._accounts_url}/oauth/v2/token"
        try:
            r = requests.post(
                url,
                data={
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=self._timeout,
            )
        except Exception as e:
            raise CatalystAuthError(f"Token refresh request failed: {e}")

        try:
            data = r.json()
        except Exception:
            raise CatalystAuthError(f"Token endpoint returned non-JSON (HTTP {r.status_code})")

        token = data.get("access_token")
        if not token:
            # Zoho reports errors in the body even with HTTP 200.
            raise CatalystAuthError(f"No access_token in response: {data}")

        expires_in = float(data.get("expires_in", 3600))
        self._access_token = token
        self._expires_at = time.time() + expires_in
        logger.info("Catalyst access token refreshed (valid ~%.0fs)", expires_in)
        return token