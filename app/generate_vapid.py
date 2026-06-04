"""
generate_vapid.py — Generuje klucze VAPID do powiadomień push.

Uruchom RAZ, wynik wklej do .env (lokalnie) i do zmiennych środowiskowych Vercela:
  VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY

  python3 app/generate_vapid.py
"""

from __future__ import annotations

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main():
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()

    # Klucz prywatny w formacie, który rozumie pywebpush (base64url z liczby prywatnej)
    priv_val = priv.private_numbers().private_value
    priv_bytes = priv_val.to_bytes(32, "big")

    # Klucz publiczny: nieskompresowany punkt (0x04 + X + Y)
    pub_bytes = pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    print("Dodaj do .env oraz do zmiennych Vercela:\n")
    print(f"VAPID_PUBLIC_KEY={b64url(pub_bytes)}")
    print(f"VAPID_PRIVATE_KEY={b64url(priv_bytes)}")
    print("VAPID_SUBJECT=mailto:zgnilyziemniak123@gmail.com")


if __name__ == "__main__":
    main()
