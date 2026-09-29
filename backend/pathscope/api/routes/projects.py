"""Projects and sites."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import ProjectIn, ProjectOut, SiteIn, SiteOut
from pathscope.db.models import Camera, Experiment, Project, Site

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(session: Session, p: Project) -> ProjectOut:
    o = ProjectOut.model_validate(p)
    o.camera_count = session.scalar(select(func.count(Camera.id)).where(Camera.project_id == p.id)) or 0
    o.experiment_count = session.scalar(select(func.count(Experiment.id)).where(Experiment.project_id == p.id)) or 0
    o.site_count = session.scalar(select(func.count(Site.id)).where(Site.project_id == p.id)) or 0
    return o


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(db_session)):
    return [_out(session, p) for p in session.scalars(select(Project).order_by(Project.updated_at.desc()))]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, session: Session = Depends(db_session)):
    p = Project(name=body.name, description=body.description, tags=body.tags)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _out(session, p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, session: Session = Depends(db_session)):
    return _out(session, get_or_404(session, Project, project_id, "Project"))


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectIn, session: Session = Depends(db_session)):
    p = get_or_404(session, Project, project_id, "Project")
    p.name, p.description, p.tags = body.name, body.description, body.tags
    session.commit()
    session.refresh(p)
    return _out(session, p)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(db_session)):
    p = get_or_404(session, Project, project_id, "Project")
    session.delete(p)
    session.commit()


@router.get("/{project_id}/sites", response_model=list[SiteOut])
def list_sites(project_id: int, session: Session = Depends(db_session)):
    get_or_404(session, Project, project_id, "Project")
    return list(session.scalars(select(Site).where(Site.project_id == project_id).order_by(Site.name)))


@router.post("/{project_id}/sites", response_model=SiteOut, status_code=201)
def create_site(project_id: int, body: SiteIn, session: Session = Depends(db_session)):
    get_or_404(session, Project, project_id, "Project")
    s = Site(project_id=project_id, name=body.name, description=body.description)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


@router.put("/{project_id}/sites/{site_id}", response_model=SiteOut)
def update_site(project_id: int, site_id: int, body: SiteIn, session: Session = Depends(db_session)):
    s = get_or_404(session, Site, site_id, "Site")
    s.name, s.description = body.name, body.description
    session.commit()
    session.refresh(s)
    return s


@router.delete("/{project_id}/sites/{site_id}", status_code=204)
def delete_site(project_id: int, site_id: int, session: Session = Depends(db_session)):
    s = get_or_404(session, Site, site_id, "Site")
    session.delete(s)
    session.commit()
