from tests.guards import check_test_target


def test_equal_urls_refused():
    assert "must not equal" in check_test_target("postgresql://a/x", "postgresql://a/x", "x_test")


def test_missing_dev_url_with_test_name_ok():
    assert check_test_target("postgresql://a/x", None, "vessels_test") is None


def test_name_without_test_refused():
    msg = check_test_target("postgresql://a/x", "postgresql://a/y", "vessels")
    assert msg and "test" in msg and "vessels" in msg


def test_name_with_test_case_insensitive_ok():
    assert check_test_target("postgresql://a/x", "postgresql://a/y", "Vessels_TEST") is None


def test_name_check_skipped_when_name_unknown():
    assert check_test_target("postgresql://a/x", "postgresql://a/y", None) is None


def test_message_never_contains_urls():
    msg = check_test_target("postgresql://u:secretpw@h/x", "postgresql://u:secretpw@h/x", "x")
    assert "secretpw" not in msg
