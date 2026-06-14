from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import Job
from app.schemas import JobRead

router = APIRouter()


@router.get("/", response_model=list[JobRead])
def list_jobs(session: Session = Depends(get_session)):
    return [
        JobRead.model_validate(j)
        for j in session.exec(select(Job).order_by(Job.created_at.desc())).all()
    ]


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    return JobRead.model_validate(job)
