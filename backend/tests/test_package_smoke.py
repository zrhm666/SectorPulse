def test_package_exposes_version() -> None:
    import sector_pulse

    assert sector_pulse.__version__ == "0.1.0"
