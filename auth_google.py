#!/usr/bin/env python3
"""
One-time Google Calendar OAuth2 Authentication Helper.

Usage:
  1. Download 'credentials.json' from Google Cloud Console (OAuth 2.0 Client IDs -> Desktop Application).
  2. Place 'credentials.json' in the project root.
  3. Run: python auth_google.py
  4. Your browser will open to grant permission. A 'token.json' file will be generated.
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def authenticate():
    cred_file = "credentials.json"
    token_file = "token.json"

    if not os.path.exists(cred_file):
        print(f"❌ '{cred_file}' not found in the current directory.")
        print("\nHow to get 'credentials.json':")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project (or select an existing one).")
        print("  3. Go to 'APIs & Services' > 'Library' and enable 'Google Calendar API'.")
        print("  4. Go to 'APIs & Services' > 'Credentials' > 'Create Credentials' > 'OAuth client ID'.")
        print("  5. Choose Application Type: 'Desktop app'.")
        print("  6. Click 'Download JSON' and save it as 'credentials.json' in this folder.")
        sys.exit(1)

    print("🔐 Starting Google OAuth flow...")
    flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_file, "w") as token:
        token.write(creds.to_json())

    print(f"✅ Successfully authenticated! Saved credentials to '{token_file}'.")
    print("Restart your bot (python main.py) and live Google Calendar scheduling will be active!")


if __name__ == "__main__":
    authenticate()
