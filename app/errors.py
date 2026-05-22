from fastapi import HTTPException
from fastapi.responses import JSONResponse


RFC = {
    400: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.1",
    401: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.2",
    403: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.4",
    404: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.5",
    405: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.6",
    409: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.10",
    415: "https://www.rfc-editor.org/rfc/rfc9110#section-15.5.16",
    500: "https://www.rfc-editor.org/rfc/rfc9110#section-15.6.1",
}

TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
}


def envelope(status: int, detail: str, code: str = "USER_ERROR") -> dict:
    return {
        "type": RFC.get(status, RFC[400]),
        "title": TITLES.get(status, "Error"),
        "status": status,
        "o:errorDetails": [{"detail": detail, "o:errorCode": code}],
    }


class NSError(HTTPException):
    def __init__(self, status: int, detail: str, code: str = "USER_ERROR"):
        super().__init__(status_code=status, detail=envelope(status, detail, code))
        self.envelope = envelope(status, detail, code)


def ns_error_response(status: int, detail: str, code: str = "USER_ERROR") -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope(status, detail, code))
