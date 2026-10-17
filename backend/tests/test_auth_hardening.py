"""Security regression tests against the existing API and auth-owned extension routes."""
import json
import logging
import os

from fastapi.testclient import TestClient
import pytest

from test_api import app_for, login


def test_idle_expiry_and_absolute_cap(bus, clock):
    with TestClient(app_for(bus, clock, session_ttl_s=4000)) as client:
        login(client)
        clock.advance(1799)
        assert client.get('/api/ward').status_code == 200
        clock.advance(1799)
        assert client.get('/api/ward').status_code == 200
        clock.advance(403)
        assert client.get('/api/ward').status_code == 401
        login(client)
        clock.advance(1800)
        assert client.get('/api/ward').status_code == 401


def test_logout_revokes_cookie_bearer_and_query(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        token = login(client)
        assert client.post('/api/session/logout', json={}).status_code == 200
        assert not client.cookies.get('sw_session')
        assert client.get('/api/ward', headers={'Authorization': 'Bearer ' + token}).status_code == 401
        assert client.get('/api/ward?token=' + token).status_code == 401


def test_lockout_cannot_be_reset_by_correct_password(bus, clock, caplog):
    with TestClient(app_for(bus, clock)) as client, caplog.at_level(logging.INFO, logger='sw_api.auth'):
        for _ in range(5):
            assert client.post('/api/session', json={'username':'priya','pin':'wrong-secret'}).status_code == 401
        assert client.post('/api/session', json={'username':'priya','pin':'4821'}).status_code == 429
        clock.advance(300)
        assert client.post('/api/session', json={'username':'priya','pin':'4821'}).status_code == 200
    assert 'wrong-secret' not in caplog.text
    assert 'login_failure' in caplog.text and 'login_success' in caplog.text


def test_scrypt_accounts_and_private_file(bus, clock, tmp_path, monkeypatch):
    from sw_api.auth import hash_password, verify_password
    secret = 'correct horse battery staple'
    encoded = hash_password(secret)
    assert encoded != hash_password(secret)
    assert secret not in encoded
    assert verify_password(secret, encoded)
    assert not verify_password('wrong', encoded)
    path = tmp_path / 'accounts.json'
    path.write_text(json.dumps({'priya': encoded}))
    path.chmod(0o600)
    monkeypatch.setenv('SW_AUTH_ACCOUNTS_FILE', str(path))
    with TestClient(app_for(bus, clock, demo_role_login=False)) as client:
        assert client.post('/api/session', json={'username':'priya','pin':'4821'}).status_code == 401
        result = client.post('/api/login', json={'username':'priya','password':secret})
        assert result.status_code == 200
        assert result.json()['role'] == 'nurse'
        assert client.get('/api/ward').status_code == 200
    path.chmod(0o644)
    with pytest.raises(ValueError):
        app_for(bus, clock)


def test_browser_form_and_fetch_csrf_rejected(bus, clock):
    with TestClient(app_for(bus, clock)) as client:
        login(client, 'operator')
        assert client.post('/api/demo/reset', headers={'Sec-Fetch-Site':'cross-site'}, json={}).status_code == 403
        assert client.post('/api/demo/reset', data={'x':'1'}).status_code == 403
        assert client.post('/api/session/logout', headers={'Origin':'null'}, json={}).status_code == 403
        assert client.post('/api/session/logout', headers={'Origin':'http://testserver'}, json={}).status_code == 200


def test_real_account_file_disables_unprovisioned_legacy_pins(bus, clock, tmp_path, monkeypatch):
    from sw_api.auth import hash_password
    path=tmp_path/'accounts.json'
    path.write_text(json.dumps({'priya':hash_password('private password for priya')})); path.chmod(0o600)
    monkeypatch.setenv('SW_AUTH_ACCOUNTS_FILE',str(path))
    with TestClient(app_for(bus,clock,demo_role_login=False)) as client:
        assert client.post('/api/session',json={'username':'admin','pin':'9012'}).status_code==401
