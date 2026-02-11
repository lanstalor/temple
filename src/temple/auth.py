"""Authentication provider setup for Temple MCP server."""

from __future__ import annotations

import logging
import time

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull

from temple.config import Settings


class TempleAuthProvider(InMemoryOAuthProvider):
    """OAuth 2.1 provider that also accepts a static API key."""

    def __init__(
        self,
        api_key: str,
        oauth_client_id: str = "",
        oauth_client_secret: str = "",
        oauth_redirect_uris: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._api_key = api_key

        if oauth_client_id and oauth_client_secret and oauth_redirect_uris:
            self.clients[oauth_client_id] = OAuthClientInformationFull(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                client_id_issued_at=int(time.time()),
                client_secret_expires_at=0,
                scope="temple",
                token_endpoint_auth_method="client_secret_post",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                redirect_uris=oauth_redirect_uris,
            )

    async def verify_token(self, token: str) -> AccessToken | None:
        # Check static API key first.
        if self._api_key and token == self._api_key:
            return AccessToken(token=token, client_id="static", scopes=["temple"])
        # Fall back to OAuth-issued tokens.
        return await super().verify_token(token)


def build_auth_provider(settings: Settings, logger: logging.Logger | None = None) -> TempleAuthProvider | None:
    """Build authentication provider from runtime settings."""
    if not settings.api_key:
        return None

    pre_registered = bool(settings.oauth_client_id and settings.oauth_client_secret)
    redirect_uris = settings.oauth_redirect_uri_list
    dynamic_registration = True

    if pre_registered:
        if not redirect_uris:
            if logger:
                logger.warning(
                    "Pre-registered OAuth client requested but no redirect URIs provided. "
                    "Falling back to open dynamic registration."
                )
            pre_registered = False
        else:
            dynamic_registration = False

    if logger:
        mode = "pre-registered client" if pre_registered else "open dynamic registration"
        logger.info("API key + OAuth 2.1 authentication enabled (%s)", mode)

    issuer_base_url = settings.base_url.strip() or "http://localhost"

    return TempleAuthProvider(
        api_key=settings.api_key,
        oauth_client_id=settings.oauth_client_id if pre_registered else "",
        oauth_client_secret=settings.oauth_client_secret if pre_registered else "",
        oauth_redirect_uris=redirect_uris if pre_registered else None,
        base_url=issuer_base_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=dynamic_registration,
            valid_scopes=["temple"],
            default_scopes=["temple"],
        ),
    )
