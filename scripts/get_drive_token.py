"""Genera un refresh token de OAuth2 para subir reportes a Google Drive.

Uso:
    uv run --with google-auth-oauthlib python scripts/get_drive_token.py

Necesita el JSON del cliente OAuth (tipo "Desktop app") descargado desde
Google Cloud Console. Por defecto lo busca como ``client_secret.json`` en la
raiz del proyecto. El script abre el navegador, pedi consentimiento y al final
imprime las variables que van en el ``.env``.

Notas:
- El scope por defecto es ``drive.file`` (no sensible). Si necesitas acceso
  total al Drive, usa ``--scope https://www.googleapis.com/auth/drive``.
- Si la pantalla de consentimiento queda en estado "Testing", el refresh token
  expira a los 7 dias. Publica la app ("In production") para evitarlo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

DEFAULT_SCOPE = "https://www.googleapis.com/auth/drive.file"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        default="client_secret.json",
        help="Ruta al JSON del cliente OAuth (Desktop app).",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="Scope OAuth a solicitar (por defecto: drive.file).",
    )
    args = parser.parse_args()

    secret_path = Path(args.client_secret)
    if not secret_path.exists():
        raise SystemExit(
            f"No se encontro {secret_path}. Descarga el JSON del cliente OAuth "
            "(tipo Desktop app) desde Google Cloud Console y guardalo ahi."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(secret_path), [args.scope]
    )
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        raise SystemExit(
            "Google no devolvio un refresh_token. Si ya habias autorizado la "
            "app, revoca el acceso en https://myaccount.google.com/permissions "
            "y volve a ejecutar el script."
        )

    print("\n=== Credenciales para tu .env ===")
    print(f"GOOGLE_OAUTH_CLIENT_ID={credentials.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={credentials.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")
    print("GOOGLE_DRIVE_FOLDER_ID=<id-de-tu-carpeta>")
    print(
        "\nRecorda: si la app esta en estado 'Testing', el refresh token expira "
        "a los 7 dias. Publica la app ('In production') para evitarlo."
    )


if __name__ == "__main__":
    main()
