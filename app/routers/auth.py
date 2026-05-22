from fastapi import APIRouter

from ..config import DEV_TOKEN

router = APIRouter(prefix="/services/rest/auth", tags=["auth"])


@router.post("/token")
def issue_token() -> dict:
    """Stub OAuth2 client-credentials token endpoint. Returns the configured dev token."""
    return {
        "access_token": DEV_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600,
    }
