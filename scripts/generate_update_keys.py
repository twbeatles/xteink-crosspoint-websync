from __future__ import annotations

import base64
import subprocess
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.b64encode(private_bytes).decode("ascii"),
        base64.b64encode(public_bytes).decode("ascii"),
    )


def set_github_secret(name: str, value: str) -> None:
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--body", value],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to set GitHub secret {name}: {proc.stderr.strip()}")
    print(f"[OK] GitHub secret set: {name}")


def main() -> int:
    priv_b64, pub_b64 = generate_keypair()
    print(f"PUBLIC_KEY_B64: {pub_b64}")
    
    set_github_secret("X3_UPDATE_PUBLIC_KEY_B64", pub_b64)
    set_github_secret("X3_UPDATE_PRIVATE_KEY_B64", priv_b64)
    print("\nKeys generated and successfully set to GitHub repository secrets!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
