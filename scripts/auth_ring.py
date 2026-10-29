#!/usr/bin/env python3
"""auth_ring.py -- Obtain and persist a valid Ring API token.

Follows RING_AUTH.md flow:
  1. Check .token.cache for a valid cached token -> if valid, END
  2. Attempt auth with OTP (from config.ring_otp or env var RING_OTP)
  3. Fall back to username/password only -> prompt user interactively

Usage:
    python scripts/auth_ring.py          # runs full flow auto-detects token cache
    RING_OTP=123456 python3 auth_ring   # use OTP from env var
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ring_doorbell import Auth as _AuthCls, Ring as _RingCls

# Ensure the parent project directory is on sys.path so `config` can be
# imported when this script is run directly (rather than via a package).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_env_keys(keys: tuple[str, ...]) -> dict[str, str]:
    """Read .env file and return requested keys as a dict."""
    env_path = _PROJECT_ROOT / ".env"
    result: dict[str, str] = {}
    for k in keys:
        result[k] = ""
    for raw_line in env_path.read_text().splitlines():
        if "=" not in raw_line or raw_line.startswith("#"):
            continue
        k, v = raw_line.split("=", 1)
        stripped = k.strip()
        if stripped in keys:
            result[stripped] = v.strip().strip('"')
    return result


def _load_cached_token(cache_path: Path) -> dict[str, Any] | None:
    """Return token dict from .token.cache path, or None if not found/invalid."""
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_token_to_cache(token: Any, cache_path: Path) -> None:
    """Persist token dict to the specified cache path."""
    token_str = json.dumps(token).strip('"')
    cache_path.write_text(token_str)


async def _test_token(auth: Any) -> bool:
    """Return True if the auth object's stored token works against live Ring."""
    try:
        test_ring = _RingCls(auth)
        await test_ring.async_update_devices()
        return True
    except OSError:
        return False


def _prompt_otp() -> str:
    """Interactive OTP prompt - blocks until user provide 4+ char code."""
    while True:
        code = input("[!] Enter your Ring 2FA OTP code: ").strip()
        if code and len(code) >= 4:
            return code
        print("    Invalid. Must be >=4 chars. Try again.")


async def authenticate(
        username: str, password: str, token_cache_file: str) -> dict[str, Any] | None:
    """Full RING_AUTH.md auth flow - returns token dict on success, None on fail.

    Steps:
      1. Check cached token from .token/cache
      2. Attempt username/password (triggers Requires2FAError on first or OTP-changed accounts)
      3. Retry with OTP - read from config.ring_otp -> env var RING_OTP -> interactive prompt
    """
    otp_code: str = ""

    # --- Step 1: Try cached token -------------------------------------------
    print("[+] Checking .token/cache...")
    cached = _load_cached_token(_PROJECT_ROOT / token_cache_file)
    if cached:
        try:
            _auth_test = _AuthCls("hedeghogCambs-auth/1.0", cached, lambda t: None, None)
            is_valid = await _test_token(_auth_test)
            if is_valid:
                print("[+] Cached token validated against live Ring. OK!")
                return cached
            print("[+] Cached token expired (revoked). Fresh auth needed.")
        except (KeyError, TypeError):
            print("[!] Failed to load cached token. Attempting fresh auth.")

    # --- Step 2: Attempt with credentials only (triggers Requires2FAError --
    print("[+] Attempting auth with username + password...")
    retry_limit = 3

    for attempt in range(1, retry_limit + 1):
        _auth_inst = _AuthCls("hedeghogCambs-auth/1.0", None, lambda t: None, None)

        try:
            await _auth_inst.async_fetch_token(username, password, otp_code=None)
            # If we got here without 2FA exception - rare but possible
            print("[+] Auth succeeded (no 2FA required).")
            return getattr(_auth_inst, "_token", None) or None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if "2fa" in str(exc).lower():
                # Expected on OTP-enabled accounts. Proceed to interactive/auth retry.
                print("[!] Requires2FAError (expected for OTP-enabled accounts.)")

                # --- Get fresh OTP code ---------------------------------------
                otp_code = _prompt_otp()
                print(f"    Attempting with OTP: {otp_code}")

                # Retry with the OTP code
                try:
                    retry_auth = _AuthCls(
                        "hedeghogCambs-auth/1.0", None, lambda t: None, None
                    )
                    await retry_auth.async_fetch_token(username, password, otp_code=otp_code)
                    print("[+] OTP auth passed!")
                    return getattr(retry_auth, "_token", None) or None
                except (OSError, ValueError, KeyError) as retry_exc:
                    if "2fa" in str(retry_exc).lower():
                        print("[!] OTP invalid - please update your authenticator " \
                        "app and try a fresh code.")
                    else:
                        print(f"[!] Unexpected error during OTP auth: {retry_exc}")

                    # Retry the OTP attempt at most once more before giving up
                    if attempt < retry_limit:
                        print(f"    Retrying (attempt {attempt+1}/{retry_limit})...")
                        continue
                    print("[!] All OTP retry attempts exhausted. Auth failed.")
                    return None
                # break out - we hit 2FA error
            else:
                # Not a 2FA error - something broken (network, creds, etc.)
                print(f"[!] Unexpected auth failure: {exc}")
                if attempt < retry_limit:
                    print("    Retrying...")
                continue

        # If we exhausted retries without success
        return None

    print("[!] All OTP retry attempts exhausted. Auth failed.")
    return None


# ── Entry Point ────────────────────────────────────────────────────────────

async def main() -> int:
    """Load credentials from .env, authenticate, persist token."""
    environment = _load_env_keys(("ring_username", "ring_password"))
    username = environment.get("ring_username", "")
    password = environment.get("ring_password", "")
    token_cache_file = "ring.token.cache"

    if not username or not password:
        print("[!] Missing ring_username or ring_password in .env")
        return 1

    print(f"[*] Username loaded from .env ({username})")
    print()

    token = await authenticate(username, password, token_cache_file)
    if token is None:
        print("[!] Authentication failed.")
        return 2

    # Persist token - cache file only
    _save_token_to_cache(token, _PROJECT_ROOT / token_cache_file)

    print()
    print(f"[+] Token saved to {token_cache_file}")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
