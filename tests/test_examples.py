"""Tests for the worked doc examples in ``examples/``."""

from __future__ import annotations

import random

import pytest

from examples.kdtree import Node, Point, build_kdtree, build_kdtree_naive, split_points


def _points(n: int, seed: int = 0) -> list[Point]:
    rng = random.Random(seed)
    return [(rng.random(), rng.random()) for _ in range(n)]


@pytest.mark.parametrize("n", [0, 1, 2, 3, 50, 257])
def test_naive_and_fixed_build_the_same_tree(n: int) -> None:
    """The memory fix must not change the tree — only what each node retains."""
    pts = _points(n)
    assert split_points(build_kdtree(pts)) == split_points(build_kdtree_naive(pts))


def test_tree_contains_every_point_once() -> None:
    """Every input point appears exactly once as a split point."""
    pts = _points(200)
    assert sorted(split_points(build_kdtree(pts))) == sorted(pts)


def test_kdtree_invariant() -> None:
    """On each node's split axis, its whole left subtree is ≤ it and right is ≥."""
    pts = _points(200)

    def check(node: Node | None, depth: int) -> None:
        if node is None:
            return
        axis = depth % 2
        assert all(p[axis] <= node.point[axis] for p in split_points(node.left))
        assert all(p[axis] >= node.point[axis] for p in split_points(node.right))
        check(node.left, depth + 1)
        check(node.right, depth + 1)

    check(build_kdtree(pts), 0)
