from collector.win_source_probe import validate_probe_url


def test_public_race_url_allowed():
    assert validate_probe_url("https://www.rikstoto.no/Spill/S2_NR_2026-10-19/V?race=9")


def test_external_host_rejected():
    assert not validate_probe_url("https://other.example/Spill/S2_NR_2026-10-19/V")


def test_http_and_credentials_rejected():
    assert not validate_probe_url("http://www.rikstoto.no/Spill/S2_NR_2026-10-19/V")
    assert not validate_probe_url("https://user:pass@www.rikstoto.no/Spill/X/V")


def test_api_and_nonrace_rejected():
    assert not validate_probe_url("https://www.rikstoto.no/api/racedays")
    assert not validate_probe_url("https://www.rikstoto.no/")
