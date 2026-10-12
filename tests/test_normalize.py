from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb.normalize import format_captured_at, item_id, normalise_url, version_id


class TestNormaliseUrl:
    def test_lowercases_scheme_and_host_but_not_path(self):
        assert normalise_url("HTTPS://Example.COM/Some/Path") == "https://example.com/Some/Path"

    def test_drops_fragment(self):
        assert normalise_url("https://example.com/a#section-2") == "https://example.com/a"

    def test_drops_trailing_slash(self):
        assert normalise_url("https://example.com/a/") == "https://example.com/a"
        assert normalise_url("https://example.com/") == "https://example.com"

    def test_strips_tracking_params_and_keeps_the_rest(self):
        url = "https://example.com/a?utm_source=x&id=42&fbclid=abc&UTM_Medium=y"
        assert normalise_url(url) == "https://example.com/a?id=42"

    def test_sorts_query_params(self):
        assert normalise_url("https://example.com/a?b=2&a=1") == "https://example.com/a?a=1&b=2"

    def test_keeps_blank_query_values(self):
        assert normalise_url("https://example.com/a?flag=&x=1") == "https://example.com/a?flag=&x=1"

    def test_drops_default_port_keeps_custom_port(self):
        assert normalise_url("https://example.com:443/a") == "https://example.com/a"
        assert normalise_url("http://example.com:80/a") == "http://example.com/a"
        assert normalise_url("http://localhost:8080/a") == "http://localhost:8080/a"

    def test_keeps_www(self):
        assert normalise_url("https://www.example.com/a") == "https://www.example.com/a"

    def test_strips_surrounding_whitespace(self):
        assert normalise_url("  https://example.com/a \n") == "https://example.com/a"

    def test_is_idempotent(self):
        once = normalise_url("HTTPS://Example.com/a/?utm_source=x&z=1&a=2#frag")
        assert normalise_url(once) == once

    @pytest.mark.parametrize("bad", ["example.com/a", "ftp://example.com/a", "mailto:a@b.c", "", "https:///a"])
    def test_rejects_non_http_urls(self, bad):
        with pytest.raises(ValueError):
            normalise_url(bad)


class TestItemId:
    def test_is_64_char_hex(self):
        value = item_id("https://example.com/a")
        assert len(value) == 64
        assert int(value, 16)
        assert item_id("https://example.com/a") != item_id("https://example.com/b")

    def test_same_page_with_tracking_noise_gives_same_item(self):
        a = item_id(normalise_url("https://example.com/a?utm_source=newsletter"))
        b = item_id(normalise_url("https://EXAMPLE.com/a/#top"))
        assert a == b

    def test_is_stable_across_runs(self):
        # Pinned so a later change to the hashing scheme is caught explicitly.
        assert item_id("https://example.com/a") == "2dce0a4c50441bfccfa9caf4b58c3cba6e06c420505dd829f0436de1aa44baac"


class TestCapturedAtAndVersionId:
    def test_formats_utc_with_millis_and_z(self):
        ts = datetime(2026, 9, 21, 14, 3, 5, 123456, tzinfo=UTC)
        assert format_captured_at(ts) == "2026-09-21T14:03:05.123Z"

    def test_converts_other_timezones_to_utc(self):
        ts = datetime(2026, 9, 21, 16, 3, 5, tzinfo=timezone(timedelta(hours=2)))
        assert format_captured_at(ts) == "2026-09-21T14:03:05.000Z"

    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError):
            format_captured_at(datetime(2026, 9, 21, 14, 3, 5))

    def test_version_id_is_item_id_colon_timestamp(self):
        ts = datetime(2026, 9, 21, 14, 3, 5, tzinfo=UTC)
        assert version_id("abc123", ts) == "abc123:2026-09-21T14:03:05.000Z"

    def test_version_ids_sort_chronologically(self):
        earlier = version_id("x", datetime(2026, 9, 21, 9, 0, 0, tzinfo=UTC))
        later = version_id("x", datetime(2026, 9, 21, 10, 0, 0, tzinfo=UTC))
        assert earlier < later
