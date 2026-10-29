# [PATCH:STAGE8-test-permissions]
"""Role permissions matrix sanity check."""
from config import (
    ROLE_PERMISSIONS, ROLE_ADMIN, ROLE_MANAGER,
    ROLE_ANNOTATOR, ROLE_REVIEWER,
)


def test_admin_has_all_critical_perms():
    p = ROLE_PERMISSIONS[ROLE_ADMIN]
    for perm in ("user.manage", "project.delete_hard", "model.manage",
                 "dataset.export", "annotation.write", "annotation.review"):
        assert perm in p


def test_manager_not_manage_users():
    p = ROLE_PERMISSIONS[ROLE_MANAGER]
    assert "user.manage" not in p
    assert "project.delete_hard" not in p
    assert "model.manage" in p


def test_annotator_minimal():
    p = ROLE_PERMISSIONS[ROLE_ANNOTATOR]
    assert "annotation.write" in p
    assert "user.manage" not in p
    assert "dataset.export" not in p


def test_reviewer_can_review():
    p = ROLE_PERMISSIONS[ROLE_REVIEWER]
    assert "annotation.review" in p
    assert "annotation.write" in p
    assert "user.manage" not in p
