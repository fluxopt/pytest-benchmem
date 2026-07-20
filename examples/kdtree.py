"""Build a 2-D k-d tree over points — a worked memory example for the docs.

A k-d tree recursively splits a set of points by alternating axes; it's the
backbone of nearest-neighbour search and spatial joins. Both builds here produce
the *same* tree, but the naive one commits a classic mistake — every node stashes
the whole sublist it was split from — so the tree retains ``O(n·log n)`` points
instead of ``O(n)``. The recursion makes it a textbook case for a flamegraph.
Both are exercised by ``tests/test_examples.py``.
"""

from __future__ import annotations

Point = tuple[float, float]


class Node:
    """A k-d tree node that keeps only its split point and children."""

    __slots__ = ("point", "left", "right")

    def __init__(self, point: Point, left: Node | None, right: Node | None) -> None:
        self.point = point
        self.left = left
        self.right = right


class RegionNode:
    """Like :class:`Node`, but also retains the sublist it was built from."""

    __slots__ = ("point", "region", "left", "right")

    def __init__(self, point: Point, region: list[Point]) -> None:
        self.point = point
        self.region = region  # ← the leak: the whole sublist stays alive
        self.left: RegionNode | None = None
        self.right: RegionNode | None = None


def build_kdtree(points: list[Point], depth: int = 0) -> Node | None:
    """Build the tree keeping only split points — ``O(n)`` memory."""
    if not points:
        return None
    ordered = sorted(points, key=lambda p: p[depth % 2])
    mid = len(ordered) // 2
    return Node(
        ordered[mid],
        build_kdtree(ordered[:mid], depth + 1),
        build_kdtree(ordered[mid + 1 :], depth + 1),
    )


def build_kdtree_naive(points: list[Point], depth: int = 0) -> RegionNode | None:
    """Build the same tree, but each node also stashes its sublist — ``O(n·log n)``."""
    if not points:
        return None
    ordered = sorted(points, key=lambda p: p[depth % 2])
    mid = len(ordered) // 2
    node = RegionNode(ordered[mid], ordered)
    node.left = build_kdtree_naive(ordered[:mid], depth + 1)
    node.right = build_kdtree_naive(ordered[mid + 1 :], depth + 1)
    return node


def split_points(node: Node | RegionNode | None) -> list[Point]:
    """Collect a tree's split points in pre-order (root, left, right)."""
    if node is None:
        return []
    return [node.point, *split_points(node.left), *split_points(node.right)]
