from fastapi import APIRouter, Depends, Request, Response

from backend.app.api.account_access import BrowserSession, SignedIn, require_browser_action
from backend.app.models.account_schemas import AccountInput, CurrentAccount, ProfileInput, RegisterInput
from backend.app.models.error_schemas import ErrorResponse
from backend.app.services.accounts import SESSION_COOKIE, SESSION_SECONDS

router = APIRouter(prefix="/auth", tags=["accounts"])
SESSION_ERRORS = {
    401: {"model": ErrorResponse, "description": "Login or session required"},
    403: {"model": ErrorResponse, "description": "Origin or request header rejected"},
}


def _secure(request):
    return (request.url.scheme == "https"
            or request.app.state.settings.app_env.lower() in ("production", "prod"))


def _set_cookie(request, response, token):
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=_secure(request), samesite="lax", path="/")


def _source(request):
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=201, response_model=CurrentAccount,
             dependencies=[Depends(require_browser_action)], responses={
                 **SESSION_ERRORS, 409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def register(body: RegisterInput, request: Request, response: Response, token: BrowserSession):
    account, issued = request.app.state.account_service.register(body, _source(request), token)
    _set_cookie(request, response, issued)
    return account


@router.post("/login", response_model=CurrentAccount, dependencies=[Depends(require_browser_action)],
             responses={**SESSION_ERRORS, 429: {"model": ErrorResponse}})
def login(body: AccountInput, request: Request, response: Response, token: BrowserSession):
    account, issued = request.app.state.account_service.login(body, _source(request), token)
    _set_cookie(request, response, issued)
    return account


@router.get("/me", response_model=CurrentAccount, responses=SESSION_ERRORS)
def me(account: SignedIn):
    return account


@router.patch("/me", response_model=CurrentAccount, responses=SESSION_ERRORS)
def update_profile(body: ProfileInput, request: Request, account: SignedIn):
    return request.app.state.account_service.update_profile(account.id, body)


@router.post("/logout", status_code=204, dependencies=[Depends(require_browser_action)], responses=SESSION_ERRORS)
def logout(request: Request, token: BrowserSession):
    request.app.state.account_service.logout(token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=_secure(request), samesite="lax", path="/")
    return response
