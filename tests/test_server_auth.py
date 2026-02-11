"""Tests for auth provider configuration."""

import logging

from temple.auth import build_auth_provider
from temple.config import Settings


def test_build_auth_provider_with_pre_registered_client():
    """Pre-registered OAuth client disables dynamic registration."""
    settings = Settings(
        api_key="test-key",
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_redirect_uris="https://example.com/callback",
        base_url="https://temple.example",
    )

    auth = build_auth_provider(settings, logger=logging.getLogger(__name__))
    assert auth is not None
    assert auth.client_registration_options is not None
    assert auth.client_registration_options.enabled is False
    assert "client-id" in auth.clients


def test_build_auth_provider_falls_back_to_dynamic_registration():
    """Missing redirect URIs falls back to dynamic client registration."""
    settings = Settings(
        api_key="test-key",
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_redirect_uris="",
    )

    auth = build_auth_provider(settings, logger=logging.getLogger(__name__))
    assert auth is not None
    assert auth.client_registration_options is not None
    assert auth.client_registration_options.enabled is True
    assert "client-id" not in auth.clients


def test_build_auth_provider_uses_localhost_issuer_when_base_url_missing():
    """Missing base URL falls back to localhost issuer for local auth routes."""
    settings = Settings(api_key="test-key")
    auth = build_auth_provider(settings, logger=logging.getLogger(__name__))
    assert auth is not None
    assert str(auth.base_url) == "http://localhost/"
