"""Sign-up, sign-in and the signed-in user's own data (alerts, bookmarks, history)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm

from ..services.auth import create_token, hash_password, verify_password
from .deps import CurrentUser, NodeDep
from .schemas import BookmarkBody, LoginBody, ProfileBody, RegisterBody, SubscriptionBody, SubscriptionPatch

router = APIRouter(tags=["account"])


def _session(node, user: dict) -> dict:
    token = create_token(user, node.settings.jwt_secret, node.settings.node_id, node.settings.jwt_ttl_hours)
    return {"access_token": token, "token_type": "bearer", "user": user}


def _login(node, request: Request, email: str, password: str) -> dict:
    key = f"{request.client.host if request.client else '?'}|{email.strip().lower()}"
    if node.login_throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try again in a few minutes")
    record = node.app.user_with_secret(email)
    if not record or not verify_password(password, record.pop("password_hash")):
        node.login_throttle.failed(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong e-mail or password")
    node.login_throttle.reset(key)
    node.app.touch_login(record["id"])
    return _session(node, node.app.user(record["id"]))


@router.post("/auth/register", status_code=201)
async def register(body: RegisterBody, node: NodeDep):
    if not node.settings.allow_signup:
        raise HTTPException(403, "Sign-up is disabled on this node")
    if node.app.user_with_secret(body.email):
        raise HTTPException(409, "An account with this e-mail already exists")
    # The very first account on a node without a configured admin becomes the admin.
    role = "admin" if not node.app.admin_exists() else "viewer"
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = node.app.create_user(body.email, body.name, password_hash, role)
    return _session(node, user)


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, node: NodeDep):
    return await run_in_threadpool(_login, node, request, body.email, body.password)


@router.post("/auth/token", include_in_schema=True)
async def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, node: NodeDep):
    """OAuth2 password flow (used by the "Authorize" button in the API docs)."""
    return await run_in_threadpool(_login, node, request, form.username, form.password)


@router.get("/auth/me")
def me(user: CurrentUser, node: NodeDep):
    return {**user, "node": node.settings.node_id}


@router.patch("/auth/me")
def update_me(body: ProfileBody, user: CurrentUser, node: NodeDep):
    if body.new_password:
        record = node.app.user_with_secret(user["email"])
        if not body.current_password or not verify_password(body.current_password, record["password_hash"]):
            raise HTTPException(400, "Current password is incorrect")
        node.app.set_password(user["id"], hash_password(body.new_password))
    if body.name:
        user = node.app.update_profile(user["id"], body.name)
    return user


# --------------------------------------------------------------------------- alerts


@router.get("/me/subscriptions")
def subscriptions(user: CurrentUser, node: NodeDep):
    return {"subscriptions": node.app.subscriptions(user["id"]), "smtp": node.notifier.configured}


@router.post("/me/subscriptions", status_code=201)
def add_subscription(body: SubscriptionBody, user: CurrentUser, node: NodeDep):
    if len(node.app.subscriptions(user["id"])) >= 25:
        raise HTTPException(400, "You can keep up to 25 alerts")
    return node.app.add_subscription(user["id"], body.query, body.mode, body.min_score)


@router.patch("/me/subscriptions/{sub_id}")
def update_subscription(sub_id: int, body: SubscriptionPatch, user: CurrentUser, node: NodeDep):
    updated = node.app.update_subscription(user["id"], sub_id, body.active, body.min_score)
    if not updated:
        raise HTTPException(404, "Alert not found")
    return updated


@router.delete("/me/subscriptions/{sub_id}", status_code=204)
def delete_subscription(sub_id: int, user: CurrentUser, node: NodeDep):
    if not node.app.delete_subscription(user["id"], sub_id):
        raise HTTPException(404, "Alert not found")


@router.post("/me/subscriptions/{sub_id}/preview")
def preview_subscription(sub_id: int, user: CurrentUser, node: NodeDep):
    """Which of the most recently ingested documents this alert would have matched."""
    subscription = next((s for s in node.app.subscriptions(user["id"]) if s["id"] == sub_id), None)
    if not subscription:
        raise HTTPException(404, "Alert not found")
    docs = node.recent_documents(30)
    candidates = [{"id": d["id"], "title": d["title"], "abstract": d.get("abstract") or "",
                   "authors": d.get("authors", []), "year": d.get("year")} for d in docs]
    return {"matches": node.notifier.match(subscription, candidates), "checked": len(candidates)}


@router.post("/me/test-email")
async def test_email(user: CurrentUser, node: NodeDep):
    if not node.notifier.configured:
        raise HTTPException(400, "This node has no SMTP server configured")
    try:
        await run_in_threadpool(node.notifier.send_test, user)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        raise HTTPException(502, f"Sending failed: {exc}") from exc
    return {"sent": True, "to": user["email"]}


@router.get("/me/notifications")
def notifications(user: CurrentUser, node: NodeDep):
    return {"notifications": node.app.notifications(user["id"])}


# --------------------------------------------------------------------------- bookmarks & history


@router.get("/me/bookmarks")
def bookmarks(user: CurrentUser, node: NodeDep):
    return {"bookmarks": node.app.bookmarks(user["id"])}


@router.put("/me/bookmarks/{doc_id}")
def add_bookmark(doc_id: str, body: BookmarkBody, user: CurrentUser, node: NodeDep):
    node.app.add_bookmark(user["id"], doc_id, body.title, body.note)
    return {"saved": doc_id}


@router.delete("/me/bookmarks/{doc_id}", status_code=204)
def remove_bookmark(doc_id: str, user: CurrentUser, node: NodeDep):
    node.app.remove_bookmark(user["id"], doc_id)


@router.get("/me/history")
def history(user: CurrentUser, node: NodeDep):
    return {"history": node.app.history(user["id"])}


@router.delete("/me/history", status_code=204)
def clear_history(user: CurrentUser, node: NodeDep):
    node.app.clear_history(user["id"])
