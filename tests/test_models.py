from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kb.models import (
    Annotations,
    CaptureRequest,
    Channel,
    DateRange,
    Enrichment,
    Item,
    Version,
    VersionStatus,
    content_hash,
)

TS = datetime(2026, 9, 21, 14, 3, 5, tzinfo=UTC)
LATER = datetime(2026, 9, 22, 9, 0, 0, tzinfo=UTC)


def make_request(url="https://Example.com/a/?utm_source=x") -> CaptureRequest:
    return CaptureRequest(url=url, channel=Channel.MANUAL)


def make_enrichment(**overrides) -> Enrichment:
    fields = dict(
        title="Title",
        summary="Summary",
        key_points=["one", "two"],
        tags=["ai/retrieval"],
        embedding=[0.1, 0.2],
        model="gpt-x",
        prompt_version="1",
        taxonomy_version=3,
        embedding_model="emb-x",
    )
    return Enrichment(**(fields | overrides))


class TestVersion:
    def test_create_derives_ids_from_normalised_url(self):
        v = Version.create(make_request(), TS, "# hello")
        assert v.item_id == Version.create(make_request("https://example.com/a"), TS, "x").item_id
        assert v.id == f"{v.item_id}:2026-09-21T14:03:05.000Z"

    def test_create_keeps_original_url_and_hashes_content(self):
        v = Version.create(make_request(), TS, "# hello")
        assert v.original_url == "https://Example.com/a/?utm_source=x"
        assert v.content_hash == content_hash("# hello")
        assert v.content == "# hello"
        assert v.status is VersionStatus.PENDING
        assert v.enrichment is None

    def test_enriched_drops_content_and_sets_status(self):
        v = Version.create(make_request(), TS, "# hello").enriched(make_enrichment())
        assert v.status is VersionStatus.ENRICHED
        assert v.content is None
        assert v.content_hash == content_hash("# hello")
        assert v.enrichment.title == "Title"

    def test_failed_keeps_content_for_retry(self):
        v = Version.create(make_request(), TS, "# hello").failed("boom")
        assert v.status is VersionStatus.FAILED
        assert v.error == "boom"
        assert v.content == "# hello"

    def test_transitions_do_not_mutate_the_original(self):
        pending = Version.create(make_request(), TS, "# hello")
        pending.enriched(make_enrichment())
        assert pending.status is VersionStatus.PENDING

    def test_round_trips_through_json(self):
        v = Version.create(make_request(), TS, "# hello").enriched(make_enrichment())
        assert Version.model_validate_json(v.model_dump_json()) == v


class TestItem:
    def test_first_capture_builds_item_from_version(self):
        v = Version.create(make_request(), TS, "# hello").enriched(make_enrichment())
        item = Item.from_version(v)
        assert item.id == v.item_id
        assert item.normalised_url == "https://example.com/a"
        assert item.original_url == v.original_url
        assert item.first_captured_at == item.captured_at == TS
        assert item.current_version_id == v.id
        assert (item.title, item.summary, item.key_points, item.tags) == (
            "Title",
            "Summary",
            ["one", "two"],
            ["ai/retrieval"],
        )
        assert item.embedding == [0.1, 0.2]
        assert item.annotations == Annotations()

    def test_later_capture_keeps_first_captured_at_and_annotations(self):
        first = Item.from_version(Version.create(make_request(), TS, "v1").enriched(make_enrichment()))
        first = first.model_copy(update={"annotations": Annotations(notes="keep me")})

        second = Version.create(make_request(), LATER, "v2").enriched(make_enrichment(title="New title"))
        item = Item.from_version(second, previous=first)

        assert item.first_captured_at == TS
        assert item.captured_at == LATER
        assert item.current_version_id == second.id
        assert item.title == "New title"
        assert item.annotations.notes == "keep me"

    def test_a_note_sent_with_a_capture_goes_below_the_items_note(self):
        noted = CaptureRequest(url="https://example.com/a", channel=Channel.EXTENSION, note="  for the talk \n")
        first = Item.from_version(Version.create(noted, TS, "v1").enriched(make_enrichment()))
        assert first.annotations.notes == "for the talk"

        follow_up = noted.model_copy(update={"note": "follow-up published"})
        item = Item.from_version(Version.create(follow_up, LATER, "v2").enriched(make_enrichment()), previous=first)
        assert item.annotations.notes == "for the talk\n\nfollow-up published"

        silent = Version.create(make_request(), LATER, "v3").enriched(make_enrichment())
        assert Item.from_version(silent, previous=item).annotations.notes == item.annotations.notes

    def test_a_retag_does_not_repeat_the_note(self):
        noted = CaptureRequest(url="https://example.com/a", channel=Channel.EXTENSION, note="once")
        v = Version.create(noted, TS, "v1").enriched(make_enrichment())
        assert v.retagged(LATER, make_enrichment()).note == ""

    def test_rejects_pending_version(self):
        with pytest.raises(ValueError):
            Item.from_version(Version.create(make_request(), TS, "# hello"))


class TestCaptureRequest:
    def test_content_and_captured_at_are_optional(self):
        r = CaptureRequest.model_validate({"url": "https://example.com", "channel": "extension"})
        assert r.content is None and r.captured_at is None
        assert r.channel is Channel.EXTENSION

    def test_note_has_a_length_limit(self):
        with pytest.raises(ValidationError):
            CaptureRequest(url="https://example.com/a", channel=Channel.EXTENSION, note="x" * 20_001)

    def test_unknown_channel_is_rejected(self):
        with pytest.raises(ValueError):
            CaptureRequest.model_validate({"url": "https://example.com", "channel": "carrier-pigeon"})


def test_date_range_is_whole_utc_days_inclusive():
    day = DateRange(start="2026-10-05", end="2026-10-05")
    assert day.contains(datetime(2026, 10, 5, 0, 0, tzinfo=UTC))
    assert day.contains(datetime(2026, 10, 5, 23, 59, 59, tzinfo=UTC))
    assert not day.contains(datetime(2026, 10, 6, tzinfo=UTC))
    assert not day.contains(datetime(2026, 10, 4, 23, 59, tzinfo=UTC))
    assert DateRange().contains(datetime(1999, 1, 1, tzinfo=UTC))
    assert DateRange(start="2026-10-05").contains(datetime(2030, 1, 1, tzinfo=UTC))


def test_date_range_must_be_ordered():
    with pytest.raises(ValidationError, match="the start date is after the end date"):
        DateRange(start="2026-10-06", end="2026-10-05")
