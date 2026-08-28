from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

MIN_PUBLIC_CELL_N = 5


class DisclosureControlError(RuntimeError):
    pass


def _dimension_key(record: dict[str, Any], dimensions: Sequence[str]) -> tuple[Any, ...]:
    values: list[Any] = []
    for dimension in dimensions:
        if dimension not in record:
            raise DisclosureControlError(f"missing disclosure dimension: {dimension}")
        value = record[dimension]
        if isinstance(value, (dict, list, set, tuple)):
            raise DisclosureControlError(f"non-scalar disclosure dimension: {dimension}")
        values.append(value)
    return tuple(values)


def build_public_count_table(
    records: Iterable[dict[str, Any]],
    *,
    dimensions: Sequence[str],
    minimum_n: int = MIN_PUBLIC_CELL_N,
) -> list[dict[str, Any]]:
    """Build a disclosure-controlled count table for public/reporting use.

    This is a reporting control only; it does not alter or delete source records.
    Cells below the approved threshold are suppressed without exposing their exact
    count. Automatic semantic combining is intentionally not attempted because it
    could change the analytical meaning of categories. A reviewer may define an
    explicit, pre-documented recode and then rebuild the table.
    """
    if minimum_n < MIN_PUBLIC_CELL_N:
        raise DisclosureControlError(
            f"minimum_n cannot be lower than {MIN_PUBLIC_CELL_N} for AI4WORK reporting"
        )
    if not dimensions:
        raise DisclosureControlError("at least one disclosure dimension is required")
    if len(set(dimensions)) != len(dimensions):
        raise DisclosureControlError("duplicate disclosure dimensions are not allowed")

    counts: Counter[tuple[Any, ...]] = Counter()
    for record in records:
        if not isinstance(record, dict):
            raise DisclosureControlError("each disclosure-control record must be an object")
        counts[_dimension_key(record, dimensions)] += 1

    output: list[dict[str, Any]] = []
    for key in sorted(counts, key=lambda item: tuple(str(value) for value in item)):
        n = counts[key]
        cell = {dimension: value for dimension, value in zip(dimensions, key)}
        if n < minimum_n:
            cell.update(
                {
                    "status": "SUPPRESSED_SMALL_CELL",
                    "n": None,
                    "display_n": f"<{minimum_n}",
                    "minimum_n": minimum_n,
                }
            )
        else:
            cell.update(
                {
                    "status": "RELEASABLE",
                    "n": n,
                    "display_n": str(n),
                    "minimum_n": minimum_n,
                }
            )
        output.append(cell)
    return output


def assert_public_table_safe(
    cells: Iterable[dict[str, Any]],
    *,
    minimum_n: int = MIN_PUBLIC_CELL_N,
) -> None:
    """Fail closed if a report cell leaks a sub-threshold exact count."""
    if minimum_n < MIN_PUBLIC_CELL_N:
        raise DisclosureControlError(
            f"minimum_n cannot be lower than {MIN_PUBLIC_CELL_N} for AI4WORK reporting"
        )

    for cell in cells:
        status = cell.get("status")
        if status == "SUPPRESSED_SMALL_CELL":
            if cell.get("n") is not None:
                raise DisclosureControlError("suppressed cell exposes exact n")
            if cell.get("display_n") != f"<{minimum_n}":
                raise DisclosureControlError("suppressed cell display is not canonical")
            continue
        if status == "RELEASABLE":
            n = cell.get("n")
            if not isinstance(n, int) or isinstance(n, bool) or n < minimum_n:
                raise DisclosureControlError("releasable cell is below minimum_n")
            if cell.get("display_n") != str(n):
                raise DisclosureControlError("releasable cell display does not match exact n")
            continue
        raise DisclosureControlError("unknown disclosure-control cell status")
