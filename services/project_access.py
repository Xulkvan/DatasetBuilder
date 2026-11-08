"""[STAGE-SEC1] Единая точка проверки доступа к проектам и изображениям."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models import ImageModel, Project, UserProjectAccess
from services.auth_service import get_current_user


ADMIN_MANAGER_ROLES = frozenset({"admin", "manager"})


def check_project_access(db: Session, project_id: int, user: dict,
                         *, allow_deleted: bool = False) -> Project:
    """Возвращает Project, если у пользователя есть доступ. Иначе 403/404.

    allow_deleted=True — разрешает доступ к проекту в корзине
    (нужно для restore/permanent_delete/empty_trash).
    """
    q = db.query(Project).filter(Project.id == project_id)
    if not allow_deleted:
        q = q.filter(Project.is_deleted.is_(False))
    proj = q.first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    if user.get("local"):
        return proj
    if user.get("role") in ADMIN_MANAGER_ROLES:
        return proj
    uid = int(user.get("id") or 0)
    if uid <= 0:
        raise HTTPException(403, {"key": "error.forbidden",
                                 "fallback": "Access denied"})
    has_direct = (db.query(UserProjectAccess)
                    .filter(UserProjectAccess.user_id == uid,
                            UserProjectAccess.project_id == project_id)
                    .first())
    if has_direct:
        return proj
    has_assigned = (db.query(ImageModel.id)
                      .filter(ImageModel.project_id == project_id,
                              ImageModel.assigned_to == uid,
                              ImageModel.is_deleted.is_(False))
                      .limit(1).first())
    if has_assigned:
        return proj
    raise HTTPException(403, {"key": "error.forbidden",
                             "fallback": "Access denied"})


# [PATCH:STAGE1:E1-ANNOTATOR] assignment scope helpers
def annotator_scoped_user(user: dict) -> bool:
    if not user or user.get('local'):
        return False
    return (user.get('role') or '') == 'annotator'


def effective_image_filter(user: dict, q):
    if not annotator_scoped_user(user):
        return q
    uid = int(user.get('id') or 0)
    if uid <= 0:
        return q
    from sqlalchemy import or_
    from models import ImageModel as _IM_ann
    return q.filter(or_(_IM_ann.assigned_to == uid,
                        _IM_ann.assigned_to.is_(None)))


def check_image_access(db: Session, image_id: int, user: dict) -> ImageModel:
    """Возвращает ImageModel, проверив доступ к его проекту."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    check_project_access(db, img.project_id, user)
    # [PATCH:STAGE1:E1-ANNOTATOR] annotator: deny foreign-assigned images
    if annotator_scoped_user(user):
        uid = int(user.get('id') or 0)
        if uid > 0 and img.assigned_to is not None and img.assigned_to != uid:
            raise HTTPException(403, {'key': 'error.forbidden',
                                     'fallback': 'Image assigned to another user'})
    return img


def require_project_access(param_name: str = "project_id"):
    """.. deprecated:: Stage 6
       Use `check_project_access` directly instead.

       [PATCH:STAGE6-C25]
    """
    """.. deprecated:: Stage 6
       Use `check_project_access` directly instead.
    """
    def _checker(request: Request,
                 db: Session = Depends(get_db),
                 user: dict = Depends(get_current_user)) -> Project:
        raw = request.path_params.get(param_name) or \
              request.query_params.get(param_name)
        if raw is None:
            raise HTTPException(400, f"{param_name} required")
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{param_name} must be integer")
        return check_project_access(db, pid, user)
    return _checker


def require_image_access():
    """.. deprecated:: Stage 6
       Use `check_image_access` directly instead.

       [PATCH:STAGE6-C25]
    """
    """.. deprecated:: Stage 6
       Use `check_image_access` directly instead.
    """
    def _checker(request: Request,
                 db: Session = Depends(get_db),
                 user: dict = Depends(get_current_user)) -> ImageModel:
        raw = request.path_params.get("image_id")
        if raw is None:
            raise HTTPException(400, "image_id required")
        try:
            iid = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "image_id must be integer")
        return check_image_access(db, iid, user)
    return _checker
