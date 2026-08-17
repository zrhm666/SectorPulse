from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_responses


def test_default_fixture_is_loaded_from_package() -> None:
    responses = load_default_fixture_responses()
    assert {"article-draft", "review:1"} <= responses.keys()
