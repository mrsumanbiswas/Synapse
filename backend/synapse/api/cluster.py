"""P2P cluster status, model rebuilds and user administration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import __version__
from .deps import Admin, Curator, NodeDep
from .schemas import PeerBody, RoleBody

router = APIRouter(tags=["cluster"])


@router.get("/health")
def health(node: NodeDep):
    return {"status": "ok", "node": node.settings.node_id, "version": __version__}


@router.get("/info")
def info(node: NodeDep):
    return {
        "node": node.settings.node_id,
        "name": node.settings.node_name,
        "version": __version__,
        "signup": node.settings.allow_signup,
        "smtp": node.notifier.configured,
        "documents": len(node.engine.meta),
        "peers": len(node.cluster.peers()),
        "model_version": node.engine.model.version if node.engine.model else None,
    }


@router.get("/cluster")
def cluster(node: NodeDep):
    """Every node of the P2P network with its shard statistics and the shared model."""
    return node.cluster_status()


@router.post("/cluster/rebuild", status_code=202)
def rebuild(node: NodeDep, user: Curator):
    if node.coordinator.running:
        return {"status": "already running"}
    node.coordinator.rebuild_in_background(f"requested by {user['email']}")
    return {"status": "started"}


@router.post("/cluster/peers", status_code=201)
def add_peer(body: PeerBody, node: NodeDep, user: Admin):
    peer = node.cluster.add_peer(body.address)
    return {"address": peer.address, "node_id": peer.node_id, "alive": peer.alive}


@router.get("/admin/users")
def users(node: NodeDep, user: Admin):
    return {"users": node.app.users()}


@router.patch("/admin/users/{user_id}")
def set_role(user_id: int, body: RoleBody, node: NodeDep, user: Admin):
    target = node.app.user(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target["role"] == "admin" and body.role != "admin":
        admins = [u for u in node.app.users() if u["role"] == "admin"]
        if len(admins) <= 1:
            raise HTTPException(400, "Keep at least one admin")
    return node.app.set_role(user_id, body.role)


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_user(user_id: int, node: NodeDep, user: Admin):
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot delete your own account here")
    node.app.delete_user(user_id)
