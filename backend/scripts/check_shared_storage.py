"""Smoke test shared feed storage against the running API.

Run with the backend pointed at Supabase:

    python scripts/check_shared_storage.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


BASE_URL = os.environ.get("RAZORWIRE_API_URL", "http://127.0.0.1:8000").rstrip("/")
USER_1 = "storage-user-1@razorpay.com"
USER_2 = "storage-user-2@razorpay.com"


def request(path: str, *, method: str = "GET", user: str = USER_1, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json", "x-dev-email": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.code} {exc.read().decode()}") from exc


def main() -> None:
    suffix = int(time.time())
    post = request(
        "/posts",
        method="POST",
        user=USER_1,
        body={
            "title": f"Shared storage smoke {suffix}",
            "kind": "clip",
            "mediaUrl": "/media/shared-storage-smoke.mp4",
            "description": "Created by user 1, liked and commented by user 2.",
            "tags": ["storage"],
        },
    )
    post_id = post["id"]

    like = request(f"/posts/{post_id}/like", method="POST", user=USER_2)
    comment = request(
        f"/posts/{post_id}/comments",
        method="POST",
        user=USER_2,
        body={"text": "visible across users"},
    )
    seen_by_user_1 = request(f"/posts/{post_id}", user=USER_1)

    assert like == {"active": True, "count": 1}
    assert comment["author"]["email"] == USER_2
    assert seen_by_user_1["likes"] == 1
    assert seen_by_user_1["comments"] == 1
    assert seen_by_user_1["liked"] is False

    print(f"ok shared storage: {post_id}")


if __name__ == "__main__":
    main()
