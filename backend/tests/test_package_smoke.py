def test_package_exposes_version() -> None:
    import sector_pulse

    assert sector_pulse.__version__ == "0.1.0"


def test_docker_image_builds_and_copies_the_frontend() -> None:
    from pathlib import Path

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=web-build /web/dist ./web/dist" in dockerfile


def test_compose_publishes_single_user_services_on_loopback_only() -> None:
    from pathlib import Path

    import yaml

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    config = yaml.safe_load(compose)

    assert '"127.0.0.1:8010:8010"' in compose
    assert '"127.0.0.1:8011:8010"' in compose
    assert '"127.0.0.1:5432:5432"' in compose
    assert config["services"]["sector-pulse-postgres"]["env_file"] == [".env"]
