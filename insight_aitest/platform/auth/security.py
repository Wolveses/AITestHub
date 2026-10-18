# -*- coding: utf-8 -*-
"""用户认证与安全工具（密码哈希 + JWT Token 签发与校验）。

密码安全：使用 Python 标准库 hashlib.pbkdf2_hmac（加盐 + 100,000 次哈希迭代），无外部 C 依赖。
Token 安全：HMAC-SHA256 JWT 实现，内置过期时间验证。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

# JWT 签名密钥（从环境变量获取或采用默认私钥）
SECRET_KEY = os.getenv("INSIGHT_JWT_SECRET", "insight_aitest_super_secret_jwt_key_2026")
ALGORITHM = "HS256"
DEFAULT_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 天有效


def hash_password(password: str) -> str:
    """加盐哈希密码。返回格式: salt$hash"""
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()
    return f"{salt}${pw_hash}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码是否匹配哈希。"""
    if not hashed_password or "$" not in hashed_password:
        return False
    try:
        salt, expected_hash = hashed_password.split("$", 1)
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            100000,
        ).hex()
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding < 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(payload: dict[str, Any], expires_in: int = DEFAULT_EXPIRE_SECONDS) -> str:
    """生成 JWT Token。"""
    header = {"alg": ALGORITHM, "typ": "JWT"}
    body = dict(payload)
    now = int(time.time())
    body["iat"] = now
    body["exp"] = now + expires_in

    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _b64encode(signature)

    return f"{signing_input}.{signature_b64}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并校验 JWT Token，无效或过期返回 None。"""
    if not token or token.count(".") != 2:
        return None
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        actual_sig = _b64decode(signature_b64)
        if not hmac.compare_digest(actual_sig, expected_sig):
            return None

        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        # 校验过期时间
        if "exp" in payload and int(time.time()) > payload["exp"]:
            return None
        return payload
    except Exception:
        return None

