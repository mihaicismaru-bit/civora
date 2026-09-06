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


def _suppressed_cell(
    *,
    dimensions: Sequence[str],
    key: tuple[Any, ...],
    minimum_n: int,
    status: str,
) -> dict[str, Any]:
    cell = {dimension: value for dimension, value in zip(dimensions, key)}
    cell.update(
        {
            "status": status,
            "n": None,
            "display_n": f"<{minimum_n}" if status == "SUPPRESSED_SMALL_CELL" else "SUPPRESSED",
            "minimum_n": minimum_n,
        }
    )
    return cell


def build_public_count_table(
    records: Iterable[dict[str, Any]],
    *,
    dimensions: Sequence[str],
    minimum_n: int = MIN_PUBLIC_CELL_N,
    protect_grand_total: bool = True,
) -> list[dict[str, Any]]:
    """Build a disclosure-controlled count table for public/reporting use.

    This is a reporting control only; it does not alter or delete source records.
    Primary cells below the approved threshold are suppressed without exposing their
    exact count. When the grand total may be known/published, a table containing
    exactly one primary-suppressed cell would allow that cell to be reconstructed by
    subtraction. In that case the smallest releasable cell is secondarily suppressed.

    Automatic semantic combining is intentionally not attempted because it could
    change the analytical meaning of categories. A reviewer may define an explicit,
    pre-documented recode and then rebuild the table.
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

    ordered_keys = sorted(counts, key=lambda item: tuple(str(value) for value in item))
    primary_suppressed = {key for key in ordered_keys if counts[key] < minimum_n}
    secondary_suppressed: set[tuple[Any, ...]] = set()

    if protect_grand_total and len(primary_suppressed) == 1:
        releasable = [key for key in ordered_keys if key not in primary_suppressed]
        if not releasable:
            raise DisclosureControlError(
                "grand-total-safe release impossible: only one populated cell is suppressed"
            )
        secondary_suppressed.add(
            min(
                releasable,
                key=lambda key: (counts[key], tuple(str(value) for value in key)),
            )
        )

    output: list[dict[str, Any]] = []
    for key in ordered_keys:
        if key in primary_suppressed:
            output.append(
                _suppressed_cell(
                    dimensions=dimensions,
                    key=key,
                    minimum_n=minimum_n,
                    status="SUPPRESSED_SMALL_CELL",
                )
            )
            continue
        if key in secondary_suppressed:
            output.append(
                _suppressed_cell(
                    dimensions=dimensions,
                    key=key,
                    minimum_n=minimum_n,
                    status="SUPPRESSED_COMPLEMENTARY",
                )
            )
            continue

        cell = {dimension: value for dimension, value in zip(dimensions, key)}
        n = counts[key]
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
    protect_grand_total: bool = True,
) -> None:
    """Fail closed if a report cell leaks a sub-threshold or reconstructable count."""
    if minimum_n < MIN_PUBLIC_CELL_N:
        raise DisclosureControlError(
            f"minimum_n cannot be lower than {MIN_PUBLIC_CELL_N} for AI4WORK reporting"
        )

    materialized = list(cells)
    primary_suppressed_count = 0
    complementary_suppressed_count = 0

    for cell in materialized:
        status = cell.get("status")
        if status == "SUPPRESSED_SMALL_CELL":
            primary_suppressed_count += 1
            if cell.get("n") is not None:
                raise DisclosureControlError("suppressed cell exposes exact n")
            if cell.get("display_n") != f"<{minimum_n}":
                raise DisclosureControlError("suppressed cell display is not canonical")
            continue
        if status == "SUPPRESSED_COMPLEMENTARY":
            complementary_suppressed_count += 1
            if cell.get("n") is not None:
                raise DisclosureControlError("complementary suppressed cell exposes exact n")
            if cell.get("display_n") != "SUPPRESSED":
                raise DisclosureControlError("complementary suppressed cell display is not canonical")
            continue
        if status == "RELEASABLE":
            n = cell.get("n")
            if not isinstance(n, int) or isinstance(n, bool) or n < minimum_n:
                raise DisclosureControlError("releasable cell is below minimum_n")
            if cell.get("display_n") != str(n):
                raise DisclosureControlError("releasable cell display does not match exact n")
            continue
        raise DisclosureControlError("unknown disclosure-control cell status")

    if protect_grand_total and primary_suppressed_count == 1 and complementary_suppressed_count < 1:
        raise DisclosureControlError(
            "single primary-suppressed cell is reconstructable from a known grand total"
        )
