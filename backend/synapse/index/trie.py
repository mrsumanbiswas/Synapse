"""A prefix tree (Trie) for fast autocomplete and spelling suggestions.

Every node remembers ``best``: the highest count stored anywhere below it. That
upper bound turns top-k completion into a best-first search that only opens the
branches that can still beat what it has found, instead of walking the whole
subtree under a short prefix like "a".
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Iterator
from typing import Any


class TrieNode:
    __slots__ = ("children", "count", "best", "value")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.count = 0  # > 0 when an entry ends at this node
        self.best = 0  # max count in this subtree
        self.value: Any = None  # optional payload, e.g. the display form of the entry


class Trie:
    def __init__(self) -> None:
        self.root = TrieNode()
        self.size = 0
        self.node_count = 1

    def __len__(self) -> int:
        return self.size

    def __contains__(self, key: str) -> bool:
        node = self._find(key)
        return node is not None and node.count > 0

    def insert(self, key: str, count: int = 1, value: Any = None) -> None:
        node = self.root
        path = [node]
        for ch in key:
            child = node.children.get(ch)
            if child is None:
                child = node.children[ch] = TrieNode()
                self.node_count += 1
            node = child
            path.append(node)
        if node.count == 0:
            self.size += 1
        node.count += count
        if value is not None:
            node.value = value
        for visited in path:
            if visited.best < node.count:
                visited.best = node.count

    def count(self, key: str) -> int:
        node = self._find(key)
        return node.count if node else 0

    def _find(self, prefix: str) -> TrieNode | None:
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def complete(self, prefix: str, limit: int = 10) -> list[tuple[str, int, Any]]:
        """Top ``limit`` entries starting with ``prefix``, most frequent first."""
        start = self._find(prefix)
        if start is None or limit <= 0:
            return []
        tie = itertools.count()
        # Heap items: (-priority, tiebreak, key, node, is_entry). Subtrees are keyed by
        # their best count, an upper bound for anything inside them.
        heap: list = [(-start.best, next(tie), prefix, start, False)]
        found: list[tuple[str, int, Any]] = []
        while heap and len(found) < limit:
            _, _, key, node, is_entry = heapq.heappop(heap)
            if is_entry:
                found.append((key, node.count, node.value))
                continue
            if node.count:
                heapq.heappush(heap, (-node.count, next(tie), key, node, True))
            for ch, child in node.children.items():
                heapq.heappush(heap, (-child.best, next(tie), key + ch, child, False))
        return found

    def fuzzy(self, word: str, max_distance: int = 2, limit: int = 5) -> list[tuple[str, int, int]]:
        """Entries within ``max_distance`` Levenshtein edits of ``word``.

        One row of the edit-distance table is computed per trie node, so shared
        prefixes are scored once, and a branch is abandoned as soon as every cell
        of its row exceeds ``max_distance``. Returns (entry, distance, count).
        """
        results: list[tuple[str, int, int]] = []
        first_row = list(range(len(word) + 1))
        stack = [(child, ch, ch, first_row) for ch, child in self.root.children.items()]
        while stack:
            node, ch, key, previous = stack.pop()
            row = [previous[0] + 1]
            for i in range(1, len(word) + 1):
                row.append(min(
                    row[i - 1] + 1,  # insertion
                    previous[i] + 1,  # deletion
                    previous[i - 1] + (word[i - 1] != ch),  # substitution
                ))
            if node.count and row[-1] <= max_distance:
                results.append((key, row[-1], node.count))
            if min(row) <= max_distance:
                for next_ch, child in node.children.items():
                    stack.append((child, next_ch, key + next_ch, row))
        results.sort(key=lambda r: (r[1], -r[2], r[0]))
        return results[:limit]

    def items(self, prefix: str = "") -> Iterator[tuple[str, int]]:
        start = self._find(prefix)
        if start is None:
            return
        stack = [(prefix, start)]
        while stack:
            key, node = stack.pop()
            if node.count:
                yield key, node.count
            for ch, child in node.children.items():
                stack.append((key + ch, child))
