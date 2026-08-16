from __future__ import annotations

import os
import sys
import uuid

# environment must be pinned before app.config is imported
os.environ["DATABASE_URL"] = "sqlite:///./test_journey.db"
os.environ["JOURNEY_SCHEDULER_ENABLED"] = "0"
os.environ.pop("JOURNEY_API_TOKEN", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app import create_app
from app.db import Base, engine

API = "/api/v0/crm"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def uid() -> str:
    return str(uuid.uuid4())


def activity(name: str, activity_id: str, events: list[dict] | None = None, init: dict | None = None, display_name: str | None = None) -> dict:
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityDisplayName": display_name or name,
        "events": events or [],
        "dependencies": [],
        "dataDependencies": [],
        "initializationData": init or {},
    }


def completion(event_name: str, next_activity_id: str | None) -> dict:
    return {"eventName": event_name, "eventType": "Completion", "nextActivityId": next_activity_id}


def activation_event(next_activity_id: str | None) -> dict:
    return {"eventName": "PlayerAdded", "eventType": "Activation", "nextActivityId": next_activity_id}


def journey_body(name: str, activities: list[dict], **extra) -> dict:
    body = {
        "journeyName": name,
        "brand": "JBCL",
        "currencyCodes": ["CLP"],
        "timeZoneId": "Chile/Continental",
        "isImmediatelyAfterPublish": True,
        "isUnlimited": True,
        "reEntryRule": {"reEntryMode": "Prohibited"},
        "activities": activities,
    }
    body.update(extra)
    return body


def create_and_publish(client: TestClient, body: dict) -> dict:
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert created.status_code == 201, created.text
    journey = created.json()
    published = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/publish"
    )
    assert published.status_code == 200, published.text
    journey["publish"] = published.json()
    return journey
