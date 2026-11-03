"""Deleting a single Version: the Item falls back to what its remaining Versions show."""

from kb.models import Item, Kind
from kb.storage import Storage


class LastVersion(ValueError):
    pass


class SessionReadOnly(ValueError):
    pass


def delete_version(storage: Storage, version_id: str) -> bool:
    """False for an unknown Version; LastVersion when the Item would have nothing left to show; SessionReadOnly
    for a Session Summary, which the KB never changes (its Summary File is the record)."""
    version = storage.get_version(version_id)
    if version is None:
        return False
    if version.kind is Kind.SESSION:
        raise SessionReadOnly("a Session Summary is read-only; delete the Session's item instead")
    versions = storage.list_versions(version.item_id)
    remaining = [v for v in versions if v.id != version_id]
    item = storage.get_item(version.item_id)
    rebuilt = Item.rebuilt(remaining, item.annotations, item.first_captured_at) if item else None
    if not remaining or (item is not None and rebuilt is None):
        raise LastVersion("this is the item's last version to show; delete the item instead")
    storage.delete_version(version_id)
    if rebuilt is not None:
        storage.put_item(rebuilt)
    return True
