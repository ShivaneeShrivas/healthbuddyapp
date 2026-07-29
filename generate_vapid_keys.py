"""Generate a VAPID keypair for web push, once, ever (per environment).

Run:
    python generate_vapid_keys.py

Then copy the two printed values into your environment as:
    HB_VAPID_PUBLIC_KEY=...
    HB_VAPID_PRIVATE_KEY=...

Keep the private key secret (server-side env var only, never shipped to the
app/browser). The public key is safe to expose to the frontend — it's how
the browser proves push messages to this server's identity.
"""
import base64

from py_vapid import Vapid02


def main():
    vapid = Vapid02()
    vapid.generate_keys()

    # Raw public key bytes, URL-safe base64, no padding — the format
    # PushManager.subscribe's applicationServerKey expects.
    public_raw = vapid.public_key.public_bytes(
        encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.X962,
        format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(public_raw).decode("utf-8").rstrip("=")

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    private_b64 = base64.urlsafe_b64encode(private_raw).decode("utf-8").rstrip("=")

    print("\nAdd these to your environment (.env / Render dashboard / etc):\n")
    print(f"HB_VAPID_PUBLIC_KEY={public_b64}")
    print(f"HB_VAPID_PRIVATE_KEY={private_b64}")
    print("\nKeep the private key secret. The public key is safe to expose.\n")


if __name__ == "__main__":
    main()
