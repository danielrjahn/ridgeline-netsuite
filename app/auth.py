from fastapi import Header, HTTPException

from .config import TOKENS
from .errors import envelope


async def require_token(authorization: str | None = Header(default=None)) -> str:
    """Validate Authorization header. Accepts Bearer <token>, and accepts (but doesn't
    validate) NetSuite-style OAuth/NLAuth headers in dev mode — both behaviors documented
    as mock-only shortcuts in CLAUDE.md sec 3."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=envelope(401, "Missing Authorization header.", "INSUFFICIENT_PERMISSION"),
        )

    scheme, _, rest = authorization.partition(" ")
    scheme = scheme.strip()

    if scheme.lower() == "bearer":
        token = rest.strip()
        if not token or token not in TOKENS:
            raise HTTPException(
                status_code=401,
                detail=envelope(401, "Invalid or unknown bearer token.", "INSUFFICIENT_PERMISSION"),
            )
        return token

    if scheme in ("OAuth", "NLAuth"):
        return "oauth-stub"

    raise HTTPException(
        status_code=401,
        detail=envelope(401, "Unsupported Authorization scheme. Use Bearer.", "INSUFFICIENT_PERMISSION"),
    )
