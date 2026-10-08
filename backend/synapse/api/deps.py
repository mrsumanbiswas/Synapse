"""Shared FastAPI dependencies: the node instance and the signed-in user."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..node import SynapseNode
from ..services.auth import decode_token, role_at_least

bearer = HTTPBearer(auto_error=False)


def get_node(request: Request) -> SynapseNode:
    return request.app.state.node


NodeDep = Annotated[SynapseNode, Depends(get_node)]


def optional_user(node: NodeDep,
                  credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict | None:
    if credentials is None:
        return None
    claims = decode_token(credentials.credentials, node.settings.jwt_secret)
    # Accounts are node-local, so only tokens this node issued are accepted.
    if not claims or claims.get("iss") != node.settings.node_id:
        return None
    return node.app.user(int(claims["sub"]))


def current_user(user: Annotated[dict | None, Depends(optional_user)]) -> dict:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_role(minimum: str):
    def checker(user: Annotated[dict, Depends(current_user)]) -> dict:
        if not role_at_least(user["role"], minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This needs the {minimum} role")
        return user

    return checker


OptionalUser = Annotated[dict | None, Depends(optional_user)]
CurrentUser = Annotated[dict, Depends(current_user)]
Curator = Annotated[dict, Depends(require_role("curator"))]
Admin = Annotated[dict, Depends(require_role("admin"))]
