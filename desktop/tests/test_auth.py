import pytest

from ftapp.services import auth_service
from ftapp.services.errors import ValidationError


def test_setup_and_login(db):
    assert not auth_service.is_setup_done(db)
    key = auth_service.run_setup(db, auth_service.SetupData(username="farouk", password="Strong123"))
    db.commit()
    assert auth_service.is_setup_done(db)
    assert len(key.split("-")) == 5
    user = auth_service.authenticate(db, "FAROUK", "Strong123")
    assert user.role == "admin"


def test_weak_password_rejected(db):
    with pytest.raises(ValidationError):
        auth_service.run_setup(db, auth_service.SetupData(username="farouk", password="123"))


def test_lockout_after_failed_attempts(db, admin):
    for _ in range(auth_service.MAX_FAILED_ATTEMPTS):
        with pytest.raises(ValidationError):
            auth_service.authenticate(db, "admin", "wrong-pass")
    with pytest.raises(ValidationError, match="مقفل"):
        auth_service.authenticate(db, "admin", "Admin1234")


def test_recovery_key_reset(db):
    key = auth_service.run_setup(db, auth_service.SetupData(username="admin", password="Admin1234"))
    db.commit()
    with pytest.raises(ValidationError):
        auth_service.reset_with_recovery_key(db, "AAAA-BBBB", "admin", "NewPass123")
    new_key = auth_service.reset_with_recovery_key(db, key.lower(), "admin", "NewPass123")
    assert new_key != key
    assert auth_service.authenticate(db, "admin", "NewPass123")


def test_cannot_remove_last_admin(db, admin):
    with pytest.raises(ValidationError):
        auth_service.update_user(db, admin, admin.id, role="seller")


def test_device_token_roundtrip(db, admin):
    token = auth_service.issue_device_token(db, admin, "Pixel", "192.168.1.5")
    db.commit()
    user, device = auth_service.resolve_token(db, token)
    assert user.id == admin.id
    auth_service.revoke_device(db, admin, device.id)
    db.commit()
    with pytest.raises(ValidationError):
        auth_service.resolve_token(db, token)
