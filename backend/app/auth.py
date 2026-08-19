"""Request authentication.

Two paths, both explicit:

    Authorization: Bearer <google_id_token>   verified, domain-restricted
    no header + DEV_AUTH_EMAIL set            local-only dev user
    X-Dev-Email + DEV_AUTH_EMAIL set          local-only second-user testing

The domain check is the actual access control here — an internal learning feed
must not accept an arbitrary Google account, so a token that verifies but carries
the wrong hosted domain is rejected rather than logged.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .config import settings
from .models import User, get_session


def _verify_google_token(token: str) -> dict[str, str]:
    """Verify signature, expiry and audience, then enforce the hosted domain."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        claims = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.google_client_id or None,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc

    email = claims.get("email", "")
    domain = claims.get("hd") or email.rpartition("@")[2]
    if settings.allowed_hd and domain != settings.allowed_hd:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"domain {domain!r} is not allowed")
    if not claims.get("email_verified", False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email is not verified")

    return {
        "email": email,
        "name": claims.get("name") or email.partition("@")[0],
        "picture": claims.get("picture") or "",
    }


def current_user(
    authorization: str | None = Header(default=None),
    x_dev_email: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    """Resolve the caller, creating the user row on first sight."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "expected 'Bearer <token>'")
        profile = _verify_google_token(token)
    elif settings.dev_auth_enabled:
        email = x_dev_email or settings.dev_auth_email
        profile = {"email": email, "name": email.partition("@")[0], "picture": ""}
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Authorization header")

    user = session.exec(select(User).where(User.email == profile["email"])).first()
    if user is None:
        user = User(email=profile["email"], name=profile["name"], picture=profile["picture"] or None)
        session.add(user)
        try:
            session.commit()
            session.refresh(user)
        except IntegrityError:
            session.rollback()
            user = session.exec(select(User).where(User.email == profile["email"])).one()
    return user
