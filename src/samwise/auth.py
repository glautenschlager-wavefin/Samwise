"""One-time OAuth flow for Google Calendar access."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import truststore

truststore.inject_into_ssl()

from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

_SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
_LOCAL_PORT = 8085


def main() -> None:
    """Authenticate with Google Calendar via browser OAuth flow."""
    # Late import so the module can be loaded without a full env.
    from samwise.config import Settings

    settings = Settings()
    client_secret = settings.google_client_secret_file

    if not client_secret:
        print(
            "Error: Set SAMWISE_GOOGLE_CLIENT_SECRET_FILE to your OAuth client secret JSON path"
        )
        print()
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Create an OAuth 2.0 Client ID (Desktop app)")
        print("  3. Download the JSON")
        print('  4. Set SAMWISE_GOOGLE_CLIENT_SECRET_FILE="/path/to/client_secret.json"')
        sys.exit(1)

    secret_path = Path(client_secret)
    if not secret_path.exists():
        print(f"Error: Client secret file not found: {client_secret}")
        sys.exit(1)

    # Show what's in the client secret so we can debug redirect_uri issues.
    with open(secret_path) as f:
        secret_data = json.load(f)
    client_type = next(iter(secret_data))  # "installed" or "web"
    client_info = secret_data[client_type]
    print(f"Client type: {client_type}")
    print(f"Client ID: {client_info.get('client_id', '?')}")
    print(f"Configured redirect URIs: {client_info.get('redirect_uris', [])}")
    print()

    redirect_uri = f"http://localhost:{_LOCAL_PORT}/"
    print(f"Samwise will use redirect URI: {redirect_uri}")

    if client_type == "web":
        print()
        print("⚠  Your client secret is for a 'Web application' — not 'Desktop app'.")
        print("   Either:")
        print(f"   a) Add {redirect_uri} to Authorized redirect URIs in Google Console")
        print("   b) Or re-create the credential as a 'Desktop app' (recommended)")
        print()

    token_path = settings.data_dir / "google_token.json"
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    print(f"Opening browser for Google Calendar authorization on port {_LOCAL_PORT}...")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), _SCOPES)
    creds = flow.run_local_server(port=_LOCAL_PORT)

    token_path.write_text(creds.to_json())
    print(f"Token saved to {token_path}")
    print("Samwise can now read your Google Calendar.")


if __name__ == "__main__":
    main()
