"""Credentials for operator-run live checks; never use a built-in account/token."""
import os


def management_headers():
    token = os.environ.get('ARCHINTEL_SERVICE_TOKEN', '').strip()
    if not token:
        raise SystemExit('Create a scoped service identity in Security & access and set ARCHINTEL_SERVICE_TOKEN for this process before running live validation.')
    return {'Authorization': 'Bearer ' + token}
