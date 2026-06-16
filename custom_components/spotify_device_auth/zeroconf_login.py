"""Spotify Connect Zeroconf login helpers (username/password "default" blob flow).

Builds the Diffie-Hellman + AES encrypted login blob and talks to a device's
Zeroconf HTTP endpoint to log a Spotify account in (``addUser``) or out
(``resetUsers``). mDNS discovery reuses Home Assistant's shared Zeroconf
instance, so no extra listener socket is created.

Crypto derived from the zerospot project and SpotifyWebApiPython's
ZeroconfConnect implementation of the "default" token type.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import b64decode, b64encode

from aiohttp import ClientSession, ClientTimeout
from Crypto.Cipher import AES
from Crypto.Hash import SHA1
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util import Counter
from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

from .const import DEFAULT_VERSION, SPOTIFY_CONNECT_TYPE

_HEADERS = {"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"}


# ---------------------------------------------------------------------------
# byte / int / base64 helpers
# ---------------------------------------------------------------------------
def _write_int(i: int, out: bytearray) -> None:
    if i < 0x80:
        out.append(i)
    else:
        out.append(0x80 | (i & 0x7F))
        out.append(i >> 7)


def _write_bytes(b: bytes, out: bytearray) -> None:
    _write_int(len(b), out)
    out.extend(b)


def _int_to_bytes(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, byteorder="big") or b"\0"


def _b64_to_int(value: str) -> int:
    return int.from_bytes(b64decode(value), "big")


# ---------------------------------------------------------------------------
# Diffie-Hellman + blob crypto
# ---------------------------------------------------------------------------
_DH_GENERATOR = 2
_DH_PRIME = int.from_bytes(
    bytes(
        [
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xC9, 0x0F, 0xDA, 0xA2, 0x21, 0x68, 0xC2,
            0x34, 0xC4, 0xC6, 0x62, 0x8B, 0x80, 0xDC, 0x1C, 0xD1, 0x29, 0x02, 0x4E, 0x08, 0x8A, 0x67,
            0xCC, 0x74, 0x02, 0x0B, 0xBE, 0xA6, 0x3B, 0x13, 0x9B, 0x22, 0x51, 0x4A, 0x08, 0x79, 0x8E,
            0x34, 0x04, 0xDD, 0xEF, 0x95, 0x19, 0xB3, 0xCD, 0x3A, 0x43, 0x1B, 0x30, 0x2B, 0x0A, 0x6D,
            0xF2, 0x5F, 0x14, 0x37, 0x4F, 0xE1, 0x35, 0x6D, 0x6D, 0x51, 0xC2, 0x45, 0xE4, 0x85, 0xB5,
            0x76, 0x62, 0x5E, 0x7E, 0xC6, 0xF4, 0x4C, 0x42, 0xE9, 0xA6, 0x3A, 0x36, 0x20, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        ]
    ),
    "big",
)

_AES_BLOCK_SIZE = 16
_AES_KEY_SIZE = 16
_AUTH_TYPE_USER_PASS = 0
_IV = [253, 81, 222, 19, 70, 203, 45, 89, 141, 68, 210, 240, 93, 20, 76, 30]


def build_login_blob(
    username: str, password: str, device_id: str, remote_public_key_b64: str
) -> tuple[str, str]:
    """Build the AES-encrypted, signed, base64 login blob.

    Returns ``(blob, client_key_b64)``. Pure CPU work; safe to call directly.
    """
    private = secrets.randbits(95 * 8)
    public = pow(_DH_GENERATOR, private, _DH_PRIME)
    client_key_b64 = b64encode(_int_to_bytes(public)).decode("utf-8")
    remote_public = _b64_to_int(remote_public_key_b64)

    username_b = username.encode("utf-8")
    password_b = password.encode("utf-8")
    device_id_b = device_id.encode("utf-8")

    # inner blob, AES-ECB encrypted with a key derived from deviceId
    blob = bytearray()
    _write_int(0x49, blob)  # 'I'
    _write_bytes(username_b, blob)
    _write_int(0x50, blob)  # 'P'
    _write_int(_AUTH_TYPE_USER_PASS, blob)
    _write_int(0x51, blob)  # 'Q'
    _write_bytes(password_b, blob)

    n_zeros = _AES_BLOCK_SIZE - (len(blob) % _AES_BLOCK_SIZE) - 1
    blob.extend([0] * n_zeros)
    blob.append(n_zeros + 1)

    blen = len(blob)
    for i in range(blen - 0x11, -1, -1):
        blob[blen - i - 1] ^= blob[blen - i - 0x11]

    secret = hashlib.sha1(device_id_b).digest()
    keys = PBKDF2(secret, username_b, 20, count=0x100, hmac_hash_module=SHA1)
    key = bytearray(hashlib.sha1(keys).digest()[:20])
    key.extend(bytes([0x00, 0x00, 0x00, 0x14]))

    cipher = AES.new(bytes(key), AES.MODE_ECB)
    encrypted_inner = bytearray()
    for pos in range(0, len(blob), _AES_BLOCK_SIZE):
        encrypted_inner.extend(cipher.encrypt(bytes(blob[pos : pos + _AES_BLOCK_SIZE])))
    inner_b64 = b64encode(encrypted_inner)

    # AES-CTR encrypt + HMAC sign using the DH shared secret
    shared = pow(remote_public, private, _DH_PRIME)
    base_key = hashlib.sha1(_int_to_bytes(shared)).digest()[:16]
    encryption_key = hmac.new(base_key, b"encryption", "sha1").digest()[:_AES_KEY_SIZE]

    ctr = Counter.new(128, initial_value=int.from_bytes(bytes(_IV), "big"))
    ctr_cipher = AES.new(encryption_key, AES.MODE_CTR, counter=ctr)
    encrypted = ctr_cipher.encrypt(inner_b64)

    checksum_key = hmac.new(base_key, b"checksum", "sha1").digest()
    checksum = hmac.new(checksum_key, encrypted, "sha1").digest()

    signed = bytearray(_IV)
    signed.extend(encrypted)
    signed.extend(checksum)
    return b64encode(signed).decode("utf-8"), client_key_b64


# ---------------------------------------------------------------------------
# mDNS discovery (blocking; run in executor with a shared Zeroconf instance)
# ---------------------------------------------------------------------------
def discover(zc: Zeroconf, timeout: float = 5.0) -> list[dict]:
    """Scan for Spotify Connect devices. Blocking — call via the executor."""
    found: list[dict] = []

    def on_change(zeroconf, service_type, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        if info is None:
            return
        props = {
            k.decode(): (v.decode() if v else "")
            for k, v in (info.properties or {}).items()
        }
        found.append(
            {
                "name": name.split(".")[0],
                "addresses": info.parsed_addresses(IPVersion.V4Only),
                "port": info.port,
                "cpath": props.get("CPath") or props.get("cpath") or "/",
                "version": props.get("Version") or props.get("version") or DEFAULT_VERSION,
            }
        )

    browser = ServiceBrowser(zc, SPOTIFY_CONNECT_TYPE, handlers=[on_change])
    try:
        time.sleep(timeout)
    finally:
        browser.cancel()
    return found


# ---------------------------------------------------------------------------
# Async device endpoints
# ---------------------------------------------------------------------------
async def async_get_info(session: ClientSession, uri: str, version: str) -> dict:
    """Call the device ``getInfo`` action."""
    async with session.get(
        uri,
        params={"action": "getInfo", "version": version},
        headers=_HEADERS,
        timeout=ClientTimeout(total=8),
    ) as resp:
        data = json.loads(await resp.text())
    if str(data.get("status")) != "101":
        raise RuntimeError(f"getInfo failed: {data}")
    return data


async def async_add_user(
    session: ClientSession,
    uri: str,
    version: str,
    username: str,
    password: str,
    login_id: str,
    info: dict,
) -> dict:
    """Call the device ``addUser`` action with the encrypted login blob."""
    blob, client_key = build_login_blob(
        username, password, info["deviceID"], info["publicKey"]
    )
    data = {
        "action": "addUser",
        "version": version,
        "tokenType": "default",
        "clientKey": client_key,
        "loginId": login_id or "",
        "userName": username,
        "blob": blob,
    }
    async with session.post(
        uri, data=data, headers=_HEADERS, timeout=ClientTimeout(total=12)
    ) as resp:
        return json.loads(await resp.text())


async def async_reset_users(session: ClientSession, uri: str, version: str) -> dict:
    """Call the device ``resetUsers`` action (sign the current user out)."""
    async with session.post(
        uri,
        data={"action": "resetUsers", "version": version},
        headers=_HEADERS,
        timeout=ClientTimeout(total=12),
    ) as resp:
        return json.loads(await resp.text())
