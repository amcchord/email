"""Shared helpers for Google OAuth authorization-code flows.

google-auth-oauthlib 1.3 enables PKCE by default. The verifier generated for
the authorization request must therefore be restored on the separate callback
request before exchanging the code.
"""

import secrets


def new_code_verifier() -> str:
    """Return an RFC 7636 verifier using URL-safe unreserved characters."""
    return secrets.token_urlsafe(64)


def build_google_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: list[str],
    *,
    code_verifier: str,
):
    """Build a Google flow with an explicit verifier that survives redirects."""
    if not code_verifier:
        raise ValueError("A PKCE code verifier is required")

    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=scopes,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
