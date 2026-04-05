"""Tests for isg_agent.core.rbac.

Comprehensive coverage of:
- Role IntEnum ordering and values
- Permission IntEnum values
- ROLE_PERMISSIONS matrix (frozensets)
- check_permission() helper
- check_role_level() helper
- require_permission() decorator
- require_role() decorator
- RBACContext dataclass and enforcement
- RBACViolation exception fields
"""

from __future__ import annotations

import pytest

from isg_agent.core.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    RBACContext,
    RBACViolation,
    Role,
    check_permission,
    check_role_level,
    require_permission,
    require_role,
)


# ---------------------------------------------------------------------------
# Role enum tests
# ---------------------------------------------------------------------------


class TestRole:
    """Tests for the Role IntEnum."""

    def test_guest_value(self) -> None:
        assert Role.GUEST == 0

    def test_viewer_value(self) -> None:
        assert Role.VIEWER == 1

    def test_operator_value(self) -> None:
        assert Role.OPERATOR == 2

    def test_admin_value(self) -> None:
        assert Role.ADMIN == 3

    def test_exactly_four_members(self) -> None:
        assert len(Role) == 4

    def test_ordering_guest_less_than_admin(self) -> None:
        assert Role.GUEST < Role.ADMIN

    def test_ordering_operator_less_than_admin(self) -> None:
        assert Role.OPERATOR < Role.ADMIN

    def test_ordering_admin_greater_than_all(self) -> None:
        for r in Role:
            if r != Role.ADMIN:
                assert Role.ADMIN > r


# ---------------------------------------------------------------------------
# Permission enum tests
# ---------------------------------------------------------------------------


class TestPermission:
    """Tests for the Permission IntEnum."""

    def test_read_exists(self) -> None:
        assert Permission.READ is not None

    def test_write_exists(self) -> None:
        assert Permission.WRITE is not None

    def test_execute_exists(self) -> None:
        assert Permission.EXECUTE is not None

    def test_admin_exists(self) -> None:
        assert Permission.ADMIN is not None

    def test_exactly_four_members(self) -> None:
        assert len(Permission) == 4


# ---------------------------------------------------------------------------
# ROLE_PERMISSIONS matrix tests
# ---------------------------------------------------------------------------


class TestRolePermissions:
    """Tests for the ROLE_PERMISSIONS matrix."""

    def test_guest_has_read_only(self) -> None:
        assert ROLE_PERMISSIONS[Role.GUEST] == frozenset({Permission.READ})

    def test_viewer_has_read_only(self) -> None:
        assert ROLE_PERMISSIONS[Role.VIEWER] == frozenset({Permission.READ})

    def test_operator_has_read_write_execute(self) -> None:
        assert ROLE_PERMISSIONS[Role.OPERATOR] == frozenset(
            {Permission.READ, Permission.WRITE, Permission.EXECUTE}
        )

    def test_admin_has_all_permissions(self) -> None:
        assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(
            {Permission.READ, Permission.WRITE, Permission.EXECUTE, Permission.ADMIN}
        )

    def test_all_roles_have_entries(self) -> None:
        for role in Role:
            assert role in ROLE_PERMISSIONS

    def test_permissions_are_frozensets(self) -> None:
        for role, perms in ROLE_PERMISSIONS.items():
            assert isinstance(perms, frozenset), f"{role} permissions not frozenset"

    def test_guest_cannot_write(self) -> None:
        assert Permission.WRITE not in ROLE_PERMISSIONS[Role.GUEST]

    def test_operator_cannot_admin(self) -> None:
        assert Permission.ADMIN not in ROLE_PERMISSIONS[Role.OPERATOR]


# ---------------------------------------------------------------------------
# check_permission() tests
# ---------------------------------------------------------------------------


class TestCheckPermission:
    """Tests for the check_permission() helper."""

    def test_admin_has_admin_permission(self) -> None:
        assert check_permission(Role.ADMIN, Permission.ADMIN) is True

    def test_admin_has_write_permission(self) -> None:
        assert check_permission(Role.ADMIN, Permission.WRITE) is True

    def test_guest_has_read_permission(self) -> None:
        assert check_permission(Role.GUEST, Permission.READ) is True

    def test_guest_lacks_write_permission(self) -> None:
        assert check_permission(Role.GUEST, Permission.WRITE) is False

    def test_guest_lacks_execute_permission(self) -> None:
        assert check_permission(Role.GUEST, Permission.EXECUTE) is False

    def test_operator_has_execute_permission(self) -> None:
        assert check_permission(Role.OPERATOR, Permission.EXECUTE) is True

    def test_operator_lacks_admin_permission(self) -> None:
        assert check_permission(Role.OPERATOR, Permission.ADMIN) is False

    def test_viewer_has_read_permission(self) -> None:
        assert check_permission(Role.VIEWER, Permission.READ) is True

    def test_viewer_lacks_write_permission(self) -> None:
        assert check_permission(Role.VIEWER, Permission.WRITE) is False


# ---------------------------------------------------------------------------
# check_role_level() tests
# ---------------------------------------------------------------------------


class TestCheckRoleLevel:
    """Tests for the check_role_level() helper."""

    def test_admin_meets_admin_level(self) -> None:
        assert check_role_level(Role.ADMIN, Role.ADMIN) is True

    def test_admin_meets_guest_level(self) -> None:
        assert check_role_level(Role.ADMIN, Role.GUEST) is True

    def test_guest_meets_guest_level(self) -> None:
        assert check_role_level(Role.GUEST, Role.GUEST) is True

    def test_guest_fails_operator_level(self) -> None:
        assert check_role_level(Role.GUEST, Role.OPERATOR) is False

    def test_viewer_fails_admin_level(self) -> None:
        assert check_role_level(Role.VIEWER, Role.ADMIN) is False

    def test_operator_meets_operator_level(self) -> None:
        assert check_role_level(Role.OPERATOR, Role.OPERATOR) is True

    def test_operator_meets_viewer_level(self) -> None:
        assert check_role_level(Role.OPERATOR, Role.VIEWER) is True


# ---------------------------------------------------------------------------
# require_permission() decorator tests
# ---------------------------------------------------------------------------


class TestRequirePermission:
    """Tests for the require_permission() decorator."""

    def test_allowed_permission_executes(self) -> None:
        @require_permission(Permission.READ)
        def read_data(role: Role) -> str:
            return "data"

        assert read_data(Role.GUEST) == "data"

    def test_denied_permission_raises(self) -> None:
        @require_permission(Permission.WRITE)
        def write_data(role: Role) -> str:
            return "data"

        with pytest.raises(RBACViolation):
            write_data(Role.GUEST)

    def test_keyword_role_arg(self) -> None:
        @require_permission(Permission.EXECUTE)
        def execute_task(role: Role) -> str:
            return "executed"

        assert execute_task(role=Role.OPERATOR) == "executed"

    def test_missing_role_raises_type_error(self) -> None:
        @require_permission(Permission.READ)
        def read_data() -> str:
            return "data"

        with pytest.raises(TypeError):
            read_data()

    def test_admin_permission_on_admin_role(self) -> None:
        @require_permission(Permission.ADMIN)
        def admin_action(role: Role) -> str:
            return "admin"

        assert admin_action(Role.ADMIN) == "admin"

    def test_admin_permission_on_operator_role_raises(self) -> None:
        @require_permission(Permission.ADMIN)
        def admin_action(role: Role) -> str:
            return "admin"

        with pytest.raises(RBACViolation):
            admin_action(Role.OPERATOR)


# ---------------------------------------------------------------------------
# require_role() decorator tests
# ---------------------------------------------------------------------------


class TestRequireRole:
    """Tests for the require_role() decorator."""

    def test_sufficient_role_executes(self) -> None:
        @require_role(Role.OPERATOR)
        def manage(role: Role) -> str:
            return "managed"

        assert manage(Role.ADMIN) == "managed"

    def test_exact_role_executes(self) -> None:
        @require_role(Role.VIEWER)
        def view(role: Role) -> str:
            return "viewed"

        assert view(Role.VIEWER) == "viewed"

    def test_insufficient_role_raises(self) -> None:
        @require_role(Role.ADMIN)
        def admin_only(role: Role) -> str:
            return "admin"

        with pytest.raises(RBACViolation):
            admin_only(Role.OPERATOR)

    def test_guest_fails_operator_requirement(self) -> None:
        @require_role(Role.OPERATOR)
        def operate(role: Role) -> str:
            return "operated"

        with pytest.raises(RBACViolation):
            operate(Role.GUEST)

    def test_missing_role_raises_type_error(self) -> None:
        @require_role(Role.GUEST)
        def simple() -> str:
            return "simple"

        with pytest.raises(TypeError):
            simple()

    def test_keyword_role_arg(self) -> None:
        @require_role(Role.VIEWER)
        def view(role: Role) -> str:
            return "viewed"

        assert view(role=Role.ADMIN) == "viewed"


# ---------------------------------------------------------------------------
# RBACContext tests
# ---------------------------------------------------------------------------


class TestRBACContext:
    """Tests for the RBACContext dataclass."""

    def test_fields_stored(self) -> None:
        ctx = RBACContext(user_id="user-1", role=Role.OPERATOR)
        assert ctx.user_id == "user-1"
        assert ctx.role == Role.OPERATOR

    def test_has_permission_true(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.ADMIN)
        assert ctx.has_permission(Permission.ADMIN) is True

    def test_has_permission_false(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.GUEST)
        assert ctx.has_permission(Permission.WRITE) is False

    def test_has_role_true(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.ADMIN)
        assert ctx.has_role(Role.OPERATOR) is True

    def test_has_role_false(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.GUEST)
        assert ctx.has_role(Role.ADMIN) is False

    def test_enforce_permission_passes(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.ADMIN)
        ctx.enforce_permission(Permission.WRITE)  # Should not raise

    def test_enforce_permission_raises(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.GUEST)
        with pytest.raises(RBACViolation):
            ctx.enforce_permission(Permission.WRITE)

    def test_enforce_role_passes(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.ADMIN)
        ctx.enforce_role(Role.OPERATOR)  # Should not raise

    def test_enforce_role_raises(self) -> None:
        ctx = RBACContext(user_id="u", role=Role.GUEST)
        with pytest.raises(RBACViolation):
            ctx.enforce_role(Role.ADMIN)

    def test_repr(self) -> None:
        ctx = RBACContext(user_id="agent-42", role=Role.OPERATOR)
        r = repr(ctx)
        assert "agent-42" in r
        assert "OPERATOR" in r


# ---------------------------------------------------------------------------
# RBACViolation exception tests
# ---------------------------------------------------------------------------


class TestRBACViolation:
    """Tests for the RBACViolation exception."""

    def test_exception_fields(self) -> None:
        exc = RBACViolation(Role.GUEST, Permission.WRITE, context="test action")
        assert exc.role == Role.GUEST
        assert exc.required == Permission.WRITE
        assert exc.context == "test action"

    def test_exception_message(self) -> None:
        exc = RBACViolation(Role.GUEST, Permission.ADMIN)
        assert "GUEST" in str(exc)
        assert "ADMIN" in str(exc)

    def test_exception_with_role_required(self) -> None:
        exc = RBACViolation(Role.VIEWER, Role.ADMIN, context="admin panel")
        assert exc.role == Role.VIEWER
        assert exc.required == Role.ADMIN
        assert "admin panel" in str(exc)

    def test_exception_without_context(self) -> None:
        exc = RBACViolation(Role.GUEST, Permission.EXECUTE)
        assert exc.context == ""
        # Should not end with ": " when context is empty
        assert str(exc).endswith("EXECUTE")
