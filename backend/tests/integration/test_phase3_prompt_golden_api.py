# ruff: noqa: E501
from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_prompt_golden_case_can_be_saved_and_listed(tmp_path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "golden.db"))
    response = client.post("/api/prompt-golden", json={"prompt_id": "writing", "prompt_version": 1, "input_hash": "abc", "expected_schema": "ArticleDraft", "result": "PASS"})
    assert response.status_code == 201
    listed = client.get("/api/prompt-golden")
    assert listed.status_code == 200
    assert listed.json()[0]["prompt_id"] == "writing"
