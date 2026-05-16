from fastapi import APIRouter
from pydantic import BaseModel

from app.services.auth_service import AuthService, verify_token

router = APIRouter(tags=["auth"])
_svc = AuthService()


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str


class MeResponse(BaseModel):
    username: str


@router.post("/auth/register", response_model=AuthResponse)
def register(body: AuthRequest) -> AuthResponse:
    try:
        token = _svc.register(body.username, body.password)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))
    return AuthResponse(token=token, username=body.username.strip())


@router.post("/auth/login", response_model=AuthResponse)
def login(body: AuthRequest) -> AuthResponse:
    try:
        token = _svc.login(body.username, body.password)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail=str(exc))
    return AuthResponse(token=token, username=body.username.strip())


@router.get("/auth/me", response_model=MeResponse)
def me(authorization: str = "") -> MeResponse:
    from fastapi import Header, HTTPException
    # Token passed as query param for simplicity
    username = verify_token(authorization.replace("Bearer ", ""))
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return MeResponse(username=username)
