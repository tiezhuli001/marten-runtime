from hashlib import sha256


def build_dedupe_key(channel_id: str, conversation_id: str, user_id: str, message_id: str) -> str:
    raw = f"{channel_id}:{conversation_id}:{user_id}:{message_id}"
    return sha256(raw.encode("utf-8")).hexdigest()
