from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import zip_longest
from typing import TypeVar

_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_MISSING = object()


def zip_strict(left: Iterable[_T1], right: Iterable[_T2]) -> Iterator[tuple[_T1, _T2]]:
    """Python 3.9 compatible subset of zip(..., strict=True)."""
    for left_item, right_item in zip_longest(left, right, fillvalue=_MISSING):
        if left_item is _MISSING or right_item is _MISSING:
            raise ValueError("zip() arguments have different lengths")
        yield left_item, right_item
