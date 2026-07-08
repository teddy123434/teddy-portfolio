# snippet: Supabase JWT 驗證中介層 + 模組別權限分級
# 節錄自家庭管理主系統後端，未經修改（不含任何真實網域/密鑰，本身即為通用實作）

from __future__ import annotations

import json
import os
import requests
import jwt
from jwt.algorithms import ECAlgorithm
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import SUPABASE_URL

_SKIP_AUTH = os.getenv("SKIP_AUTH", "").strip().lower() in {"1", "true", "yes"}
_TEST_USER_UUID = "00000000-0000-0000-0000-000000000001"

_bearer = HTTPBearer(auto_error=False)

# Cache the public key fetched from Supabase JWKS at first use
_supabase_public_key = None


def _get_supabase_public_key():
    global _supabase_public_key
    if _supabase_public_key is not None:
        return _supabase_public_key
    jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    resp = requests.get(jwks_url, timeout=5)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    if not keys:
        raise RuntimeError("Supabase JWKS returned no keys")
    _supabase_public_key = ECAlgorithm.from_jwk(json.dumps(keys[0]))
    return _supabase_public_key


def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if _SKIP_AUTH:
        return {
            "user_id": _TEST_USER_UUID,
            "is_admin": True,
            "app_metadata": {"role": "admin"},
        }

    if not SUPABASE_URL:
        raise HTTPException(status_code=500, detail="Auth not configured")

    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    try:
        public_key = _get_supabase_public_key()
        payload = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auth error: {exc}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")

    app_metadata = payload.get("app_metadata") or {}
    user_metadata = payload.get("user_metadata") or {}
    return {
        "user_id": user_id,
        "is_admin": app_metadata.get("role") == "admin",
        "app_metadata": app_metadata,
        "user_metadata": user_metadata,
    }


def require_admin(user: dict = Depends(verify_jwt)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="僅限管理員操作")
    return user


from typing import Callable

LEVEL_ORDER = {"none": 0, "viewer": 1, "user": 2, "admin": 3}
MODULES = ["ledger", "vital", "inventory"]


def require_module(module: str, min_level: str) -> Callable[[dict], dict]:
    """FastAPI 依賴工廠：要求 user 對 `module` 至少有 `min_level` 權限。
    role==admin 短路為全模組 admin。permissions 缺值視為 none。"""
    threshold = LEVEL_ORDER[min_level]

    def _dep(user: dict = Depends(verify_jwt)) -> dict:
        if user.get("is_admin"):
            return user
        perms = (user.get("app_metadata") or {}).get("permissions") or {}
        level = perms.get(module, "none")
        if LEVEL_ORDER.get(level, 0) < threshold:
            raise HTTPException(
                status_code=403,
                detail=f"權限不足：{module} 需要 {min_level} 以上",
            )
        return user

    return _dep
