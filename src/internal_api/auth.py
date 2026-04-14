import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from config import DOSE_BOT_TOKEN, NEW_BOT_TOKEN, PROFESSOR_BOT_TOKEN

BOT_AUTH_MAX_SKEW_SECONDS = 300


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    repeats = (len(data) + len(key) - 1) // len(key)
    key_stream = (key * repeats)[:len(data)]
    return bytes(a ^ b for a, b in zip(data, key_stream))


def _derive_encryption_key(bot_token: str, timestamp: str, nonce: str) -> bytes:
    seed = f"{timestamp}:{nonce}:{bot_token}:bot-auth-v1".encode("utf-8")
    return hashlib.sha256(seed).digest()


def _decrypt_token(token_enc: str, timestamp: str, nonce: str, bot_token: str) -> str:
    try:
        encrypted = base64.urlsafe_b64decode(token_enc.encode("ascii"))
        key = _derive_encryption_key(bot_token, timestamp, nonce)
        token_bytes = _xor_bytes(encrypted, key)
        return token_bytes.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid encrypted bot token") from exc


def _allowed_bot_tokens() -> list[str]:
    tokens: list[str] = []
    for token in (PROFESSOR_BOT_TOKEN, DOSE_BOT_TOKEN, NEW_BOT_TOKEN):
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def bot_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:10]


def bot_label(token: str) -> str:
    if token == PROFESSOR_BOT_TOKEN:
        return f"professor:{bot_fingerprint(token)}"
    if token == DOSE_BOT_TOKEN:
        return f"dose:{bot_fingerprint(token)}"
    if token == NEW_BOT_TOKEN:
        return f"new:{bot_fingerprint(token)}"
    return f"unknown:{bot_fingerprint(token)}"


@dataclass(frozen=True)
class InternalBotAuthContext:
    token: str
    label: str


def get_internal_bot_auth_context(request: Request) -> InternalBotAuthContext:
    timestamp = request.headers.get("X-Bot-Timestamp")
    nonce = request.headers.get("X-Bot-Nonce")
    token_enc = request.headers.get("X-Bot-Token-Enc")
    signature = request.headers.get("X-Bot-Signature")
    if not timestamp or not nonce or not token_enc or not signature:
        raise HTTPException(status_code=401, detail="Missing bot auth headers")

    try:
        ts = int(timestamp)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid bot timestamp") from exc

    if abs(int(time.time()) - ts) > BOT_AUTH_MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Expired bot auth timestamp")

    configured_tokens = _allowed_bot_tokens()
    if not configured_tokens:
        raise HTTPException(status_code=500, detail="No bot tokens configured")

    payload = f"{timestamp}:{nonce}:{token_enc}"
    for candidate in configured_tokens:
        expected_sig = hmac.new(candidate.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            continue
        decrypted_token = _decrypt_token(token_enc, timestamp, nonce, candidate)
        if hmac.compare_digest(decrypted_token, candidate):
            context = InternalBotAuthContext(token=candidate, label=bot_label(candidate))
            request.state.internal_bot_auth = context
            return context

    raise HTTPException(status_code=401, detail="Invalid bot auth")
