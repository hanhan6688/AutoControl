from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LoginAccount
from app.schemas import LoginAccountCreateRequest, LoginAccountResponse, LoginAccountUpdateRequest

router = APIRouter(prefix="/api/login-accounts", tags=["login-accounts"])


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}******{value[-2:]}"


def _to_response(account: LoginAccount) -> LoginAccountResponse:
    return LoginAccountResponse(
        id=account.id,
        platform=account.platform,
        label=account.label,
        login_id=account.login_id,
        password_masked=_mask_secret(account.password),
        note=account.note,
        use_for_autoglm=account.use_for_autoglm,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.get("", response_model=list[LoginAccountResponse])
def list_login_accounts(db: Session = Depends(get_db)) -> list[LoginAccountResponse]:
    accounts = db.query(LoginAccount).order_by(LoginAccount.platform, LoginAccount.label).all()
    return [_to_response(account) for account in accounts]


@router.post("", response_model=LoginAccountResponse)
def create_login_account(
    payload: LoginAccountCreateRequest,
    db: Session = Depends(get_db),
) -> LoginAccountResponse:
    account = LoginAccount(
        platform=payload.platform,
        label=payload.label,
        login_id=payload.login_id,
        password=payload.password,
        note=payload.note or None,
        use_for_autoglm=payload.use_for_autoglm,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.put("/{account_id}", response_model=LoginAccountResponse)
def update_login_account(
    account_id: int,
    payload: LoginAccountUpdateRequest,
    db: Session = Depends(get_db),
) -> LoginAccountResponse:
    account = db.get(LoginAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号配置不存在")

    account.platform = payload.platform
    account.label = payload.label
    account.login_id = payload.login_id
    if payload.password:
        account.password = payload.password
    account.note = payload.note or None
    account.use_for_autoglm = payload.use_for_autoglm
    db.commit()
    db.refresh(account)
    return _to_response(account)


@router.delete("/{account_id}")
def delete_login_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    account = db.get(LoginAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号配置不存在")
    db.delete(account)
    db.commit()
    return {"deleted": account_id}
