"""The Owner's Note on one Item, edited as a whole."""

from kb.models import Item, Kind
from kb.storage import Storage


def write_note(storage: Storage, item_id: str, notes: str) -> Item | None:
    """Replace the Item's Note; an empty one clears it. None for an unknown Item, ValueError for a Thought."""
    item = storage.get_item(item_id)
    if item is None:
        return None
    if item.media_type is Kind.THOUGHT:
        raise ValueError("a Thought has no note; edit the Thought instead")
    annotations = item.annotations.model_copy(update={"notes": notes.replace("\r\n", "\n").strip()})
    updated = item.model_copy(update={"annotations": annotations})
    storage.put_item(updated)
    return updated
