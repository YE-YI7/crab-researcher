"""Regression coverage for the weekly-report route contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import reports
from app.api.v2 import notifications
from app.core.security import get_current_user


def test_weekly_reports_does_not_collide_with_report_detail_route():
    app = FastAPI()
    # Preserve production ordering: the legacy report router is mounted first.
    app.include_router(reports.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1}

    response = TestClient(app).get("/api/weekly-reports?limit=4")

    assert response.status_code == 200
    assert response.json() == {"reports": []}
