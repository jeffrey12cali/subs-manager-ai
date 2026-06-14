from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import Setting

router = APIRouter()


@router.get("/", response_model=list[Setting])
def list_settings(session: Session = Depends(get_session)):
    return session.exec(select(Setting)).all()


@router.put("/{key}", response_model=Setting)
def set_setting(key: str, value: str, session: Session = Depends(get_session)):
    setting = session.get(Setting, key) or Setting(key=key, value=value)
    setting.value = value
    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting
