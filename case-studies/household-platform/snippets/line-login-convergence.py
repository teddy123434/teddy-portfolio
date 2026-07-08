# snippet: 三合一登入收斂（LINE LIFF / LINE 瀏覽器 OAuth / Google+Magic Link → 同一份 Supabase JWT）
# 節錄自 Auth Portal 後端，已移除與收斂邏輯無關的管理後台端點（使用者列表、角色/權限管理等），
# 並將內部服務代號改為通用佔位（例如 @line.app.local 這類假 email 網域僅為示意）

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import (
    MINIAPP_CHANNEL_ID,
    LINE_PORTAL_CHANNEL_ID,
    LINE_PORTAL_CHANNEL_SECRET,
    PORTAL_URL,
    SUPABASE_JWT_SECRET,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from app.core.database import get_db
from app.core.models import UserLineBinding

router = APIRouter()

LINE_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"
TOKEN_TTL = 3600


class LineExchangeRequest(BaseModel):
    id_token: str


class LineExchangeResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str


def _admin_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _admin_create_user(email: str, user_metadata: dict) -> str:
    """Create a Supabase auth user; returns user_id string."""
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        json={"email": email, "email_confirm": True, "user_metadata": user_metadata},
        headers=_admin_headers(),
        timeout=10.0,
    )
    if not resp.is_success:
        raise HTTPException(500, f"create_user failed: {resp.text}")
    return resp.json()["id"]


def _admin_generate_link(email: str, redirect_to: str) -> str:
    """Returns the action_link URL for magic-link based session establishment."""
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/admin/generate_link",
        json={"type": "magiclink", "email": email, "options": {"redirect_to": redirect_to}},
        headers=_admin_headers(),
        timeout=10.0,
    )
    if not resp.is_success:
        raise HTTPException(500, f"generate_link failed: {resp.text}")
    return resp.json()["action_link"]


def _verify_line_token(id_token: str) -> tuple[str, str, str]:
    """路徑一：LINE LIFF token 驗證。回傳 (line_uid, display_name, picture_url)。"""
    resp = httpx.post(
        LINE_VERIFY_URL,
        data={"id_token": id_token, "client_id": MINIAPP_CHANNEL_ID},
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired LIFF token")

    body = resp.json()
    channel_id = str(body.get("client_id") or body.get("aud") or "")
    if channel_id != str(MINIAPP_CHANNEL_ID):
        raise HTTPException(status_code=401, detail="Token client_id mismatch")

    return body["sub"], body.get("name", ""), body.get("picture", "")


def _get_or_create_user(
    db: Session, line_uid: str, display_name: str = "", picture_url: str = ""
) -> tuple[uuid.UUID, dict[str, Any]]:
    """LINE UID ↔ Supabase user_id 的對照與建立邏輯。三條登入路徑最終都會走到這裡。"""
    binding = db.query(UserLineBinding).filter_by(line_uid=line_uid).first()

    if binding:
        user_id = binding.user_id
        if display_name and binding.line_display_name != display_name:
            binding.line_display_name = display_name
            db.commit()
    else:
        # 第一次見到這個 LINE UID：用假 email 建立一個 Supabase 使用者
        resp = httpx.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            json={"email": f"{line_uid}@line.app.local", "email_confirm": True},
            headers=_admin_headers(),
            timeout=10.0,
        )
        if not resp.is_success:
            raise HTTPException(500, f"create_user failed: {resp.text}")
        user_id = uuid.UUID(resp.json()["id"])

        db.add(UserLineBinding(
            user_id=user_id,
            line_uid=line_uid,
            line_display_name=display_name or None,
            line_picture_url=picture_url or None,
        ))
        db.commit()

    resp = httpx.get(
        f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=_admin_headers(),
        timeout=10.0,
    )
    app_metadata = resp.json().get("app_metadata") or {} if resp.is_success else {}
    return user_id, app_metadata


def _build_jwt(user_id: uuid.UUID, app_metadata: dict[str, Any]) -> str:
    """收斂點：不論從哪條路徑來，最後都簽出同一種 Supabase 相容 JWT。"""
    now = int(time.time())
    payload = {
        "iss": "supabase",
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + TOKEN_TTL,
        "app_metadata": app_metadata,
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


@router.post("/line-exchange", response_model=LineExchangeResponse)
def line_exchange(body: LineExchangeRequest, db: Session = Depends(get_db)):
    """路徑一：LINE LIFF Mini App 內建的 token 交換。"""
    line_uid, display_name, picture_url = _verify_line_token(body.id_token)
    user_id, app_metadata = _get_or_create_user(db, line_uid, display_name, picture_url)
    token = _build_jwt(user_id, app_metadata)
    return LineExchangeResponse(access_token=token, expires_in=TOKEN_TTL, token_type="bearer")


def _exchange_line_code(code: str, redirect_uri: str) -> dict:
    """路徑二：LINE 瀏覽器版 OAuth，用 authorization code 換 ID token。"""
    token_res = httpx.post(
        "https://api.line.me/oauth2/v2.1/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": LINE_PORTAL_CHANNEL_ID,
            "client_secret": LINE_PORTAL_CHANNEL_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    if token_res.status_code != 200:
        raise HTTPException(400, f"LINE token exchange failed: {token_res.text}")
    id_token = token_res.json().get("id_token")
    if not id_token:
        raise HTTPException(400, "No ID token returned from LINE")
    return jwt.decode(
        id_token,
        LINE_PORTAL_CHANNEL_SECRET,
        algorithms=["HS256"],
        audience=str(LINE_PORTAL_CHANNEL_ID),
    )


class LineOAuthRequest(BaseModel):
    code: str
    redirect_uri: str


@router.post("/line-oauth")
def line_oauth(body: LineOAuthRequest, db: Session = Depends(get_db)):
    """路徑二：LINE 瀏覽器版 OAuth 完整流程，最後透過 magic link 建立 Supabase session。"""
    payload = _exchange_line_code(body.code, body.redirect_uri)
    line_uid: str = payload["sub"]
    display_name: str = payload.get("name") or ""
    picture_url: str = payload.get("picture") or ""
    email = f"{line_uid}@line.app.local"

    binding = db.query(UserLineBinding).filter_by(line_uid=line_uid).first()
    if not binding:
        new_uid = _admin_create_user(
            email,
            {"line_uid": line_uid, "line_display_name": display_name, "line_picture_url": picture_url},
        )
        db.add(UserLineBinding(
            user_id=uuid.UUID(new_uid),
            line_uid=line_uid,
            line_display_name=display_name,
            line_picture_url=picture_url,
        ))
        db.commit()

    # 路徑三（Google OAuth / Email Magic Link）直接由 Supabase 原生處理，
    # 不需要這個收斂函式；三條路徑的共同終點都是「取得 user_id 後簽發/建立 session」。
    action_link = _admin_generate_link(email, PORTAL_URL)
    return {"action_link": action_link}
