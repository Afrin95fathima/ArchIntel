def sign_in_owner(client):
    client.headers['X-ArchIntel-Request'] = '1'
    key = (client.app.state.config.data_dir/'security-bootstrap.key').read_text().strip()
    response = client.post('/api/v1/security/bootstrap', json={
        'username':'test-owner', 'password':'test-owner-password-2026', 'bootstrap_key':key})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response.json()
