from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.faq.routers.faq_router import router as faq_router


REMOVED_PATHS = {
    "/api/faqs/candidates/list",
    "/api/faqs/candidates/{candidate_id}",
    "/api/faqs/candidates/{candidate_id}/review",
    "/api/faqs/synthesis",
}


def test_faq_candidate_and_synthesis_routes_are_absent():
    app = FastAPI()
    app.include_router(faq_router, prefix="/api")

    assert REMOVED_PATHS.isdisjoint(app.openapi()["paths"])

    client = TestClient(app)
    assert client.get("/api/faqs/candidates/list").status_code == 404
    assert client.get("/api/faqs/candidates/candidate-1").status_code == 404
    assert client.post("/api/faqs/candidates/candidate-1/review", json={}).status_code == 404
    # The dynamic GET /faqs/{faq_id} owns this path shape, so Starlette reports
    # that POST is unsupported even though no synthesis operation remains.
    assert client.post("/api/faqs/synthesis", json={}).status_code == 405
