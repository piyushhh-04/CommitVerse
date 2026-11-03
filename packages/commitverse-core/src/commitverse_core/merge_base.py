"""Commit graph ancestry and merge-base discovery."""

from commitverse_core.commits import read_commit
from commitverse_core.repository import Repository


class MergeBaseError(ValueError):
    """Raised for invalid or cyclic commit graphs."""


def _ancestors(repository: Repository, start: str) -> dict[str, int]:
    distances: dict[str, int] = {}
    active: set[str] = set()
    def visit(object_id: str, distance: int) -> None:
        if object_id in active:
            raise MergeBaseError(f"cyclic commit history at {object_id}")
        if object_id in distances and distances[object_id] <= distance:
            return
        distances[object_id] = distance
        active.add(object_id)
        try:
            commit = read_commit(repository.objects_dir, object_id)
        except (OSError, ValueError) as error:
            raise MergeBaseError(f"cannot read commit {object_id}: {error}") from error
        try:
            for parent in commit.parent_ids:
                visit(parent, distance + 1)
        finally:
            active.remove(object_id)

    visit(start, 0)
    return distances


def is_ancestor(repository: Repository, ancestor: str, descendant: str) -> bool:
    return ancestor in _ancestors(repository, descendant)


def find_merge_base(repository: Repository, first: str, second: str) -> str | None:
    """Return a deterministic nearest common ancestor, or None."""
    left = _ancestors(repository, first)
    right = _ancestors(repository, second)
    common = set(left) & set(right)
    if not common:
        return None
    return min(common, key=lambda value: (max(left[value], right[value]), left[value] + right[value], value))
