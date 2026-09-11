from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from playwright.sync_api import FrameLocator, Locator, Page

from understudy.artifact.models import (
    AccessibilityStrategy,
    AttributeStrategy,
    CellSelect,
    ColumnValueRowMatch,
    CssStrategy,
    DescendantSelect,
    LocatorStrategy,
    RowLabelMatch,
    SurfaceContext,
    TableRelationStrategy,
    Target,
    TextStrategy,
)
from understudy.surface.base import (
    ResolvedTarget,
    TargetResolutionError,
)


_BINDING = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_ATTRIBUTE_NAME = re.compile(r"^[a-zA-Z_:][-a-zA-Z0-9_:.]*$")


def _lookup(values: dict[str, Any], path: str) -> Any:
    current: Any = values

    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"missing runtime value {path!r}")
        current = current[part]

    return current


def _render(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        return str(_lookup(values, match.group(1)))

    return _BINDING.sub(replace, template)


def _css_attribute(attribute: str, value: str) -> str:
    if not _ATTRIBUTE_NAME.fullmatch(attribute):
        raise ValueError(f"invalid attribute name {attribute!r}")

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attribute}="{escaped}"]'


def _exact(match: str) -> bool:
    return match == "exact"


class PlaywrightWebSurface:
    """Resolves typed artifact locators against a Playwright page."""

    def __init__(
        self,
        page: Page,
        contexts: dict[str, SurfaceContext],
    ) -> None:
        self._page = page
        self._contexts = contexts

    def navigate(self, url: str) -> None:
        self._page.goto(url)

    def is_visible(self, target: ResolvedTarget) -> bool:
        return target.present and self._handle(target).is_visible()

    def is_enabled(self, target: ResolvedTarget) -> bool:
        return target.present and self._handle(target).is_enabled()

    def enter_text(self, target: ResolvedTarget, value: str) -> None:
        self._handle(target).fill(value)

    def activate(self, target: ResolvedTarget) -> None:
        self._handle(target).click()

    def press_key(self, target: ResolvedTarget, key: str) -> None:
        self._handle(target).press(key)

    def read_text(self, target: ResolvedTarget) -> str:
        return self._handle(target).inner_text()

    def read_value(self, target: ResolvedTarget) -> str:
        return self._handle(target).input_value()

    def resolve_target(
        self,
        target_ref: str,
        target: Target,
        values: dict[str, Any],
    ) -> ResolvedTarget:
        root = self._resolve_context(target.context_ref, values)
        observed: list[str] = []

        for strategy in self._primary_first(target):
            locator = self._compile(root, strategy, values)
            count = locator.count()
            observed.append(f"{strategy.id}={count}")

            if (
                count > 0
                and target.expected_matches.min
                <= count
                <= target.expected_matches.max
            ):
                status = (
                    "primary"
                    if strategy.id
                    == target.drift_policy.primary_strategy_id
                    else "degraded"
                )
                return ResolvedTarget(
                    target_ref=target_ref,
                    status=status,
                    strategy_id=strategy.id,
                    match_count=count,
                    handle=locator,
                )

        if target.drift_policy.no_resolution == "condition_not_present":
            return ResolvedTarget(
                target_ref=target_ref,
                status="absent",
                strategy_id=None,
                match_count=0,
                handle=None,
            )

        details = ", ".join(observed)
        raise TargetResolutionError(
            f"target {target_ref!r} did not resolve uniquely ({details})"
        )

    def _resolve_context(
        self,
        context_ref: str,
        values: dict[str, Any],
    ) -> FrameLocator:
        context = self._contexts[context_ref]
        observed: list[str] = []

        for strategy in context.strategies:
            if isinstance(strategy, AttributeStrategy):
                value = (
                    strategy.value
                    if strategy.value is not None
                    else _render(strategy.value_template or "", values)
                )
                selector = _css_attribute(
                    strategy.attribute,
                    value,
                )
            else:
                selector = strategy.value

            frames = self._page.locator(selector)
            count = frames.count()
            observed.append(f"{strategy.id}={count}")

            if (
                count > 0
                and context.expected_matches.min
                <= count
                <= context.expected_matches.max
            ):
                return frames.content_frame

        details = ", ".join(observed)
        raise TargetResolutionError(
            f"surface context {context_ref!r} did not resolve uniquely "
            f"({details})"
        )

    @staticmethod
    def _primary_first(target: Target) -> Iterable[LocatorStrategy]:
        primary_id = target.drift_policy.primary_strategy_id
        primary = next(
            strategy
            for strategy in target.strategies
            if strategy.id == primary_id
        )
        yield primary

        for strategy in target.strategies:
            if strategy.id != primary_id:
                yield strategy

    def _compile(
        self,
        root: FrameLocator | Locator,
        strategy: LocatorStrategy,
        values: dict[str, Any],
    ) -> Locator:
        if isinstance(strategy, AccessibilityStrategy):
            return root.get_by_role(
                strategy.role,  # type: ignore[arg-type]
                name=strategy.name,
                exact=_exact(strategy.match),
            )

        if isinstance(strategy, TextStrategy):
            value = (
                strategy.value
                if strategy.value is not None
                else str(_lookup(values, strategy.value_from or ""))
            )
            scope = (
                root.locator(strategy.within_css)
                if strategy.within_css
                else root
            )
            return scope.get_by_text(value, exact=_exact(strategy.match))

        if isinstance(strategy, AttributeStrategy):
            value = (
                strategy.value
                if strategy.value is not None
                else _render(strategy.value_template or "", values)
            )
            return root.locator(_css_attribute(strategy.attribute, value))

        if isinstance(strategy, CssStrategy):
            return root.locator(strategy.value)

        if isinstance(strategy, TableRelationStrategy):
            return self._compile_table_relation(root, strategy, values)

        raise TypeError(f"unsupported locator strategy: {strategy!r}")

    def _compile_table_relation(
        self,
        root: FrameLocator | Locator,
        strategy: TableRelationStrategy,
        values: dict[str, Any],
    ) -> Locator:
        table = root.get_by_role(
            "table",
            name=strategy.table_anchor,
            exact=True,
        )

        if table.count() != 1:
            return table

        headers = [
            text.strip()
            for text in table.locator("thead th, thead td").all_inner_texts()
        ]
        rows = table.locator("tbody tr")
        row_match = strategy.row_match

        if isinstance(row_match, ColumnValueRowMatch):
            column = self._column_index(headers, row_match.column_header)
            expected = (
                row_match.equals
                if row_match.equals is not None
                else str(_lookup(values, row_match.equals_from or ""))
            )
            rows = rows.filter(
                has=root.locator(f"td:nth-child({column + 1})").get_by_text(
                    expected,
                    exact=True,
                )
            )
        elif isinstance(row_match, RowLabelMatch):
            rows = rows.filter(
                has=root.get_by_role(
                    "rowheader",
                    name=row_match.label,
                    exact=_exact(row_match.match),
                )
            )

        select = strategy.select

        if isinstance(select, DescendantSelect):
            return rows.get_by_role(
                select.role,  # type: ignore[arg-type]
                name=select.name,
                exact=_exact(select.match),
            )

        if isinstance(select, CellSelect):
            column = self._column_index(headers, select.column_header)
            return rows.locator(
                f":scope > th:nth-child({column + 1}), "
                f":scope > td:nth-child({column + 1})"
            )

        raise TypeError(f"unsupported table selection: {select!r}")

    @staticmethod
    def _column_index(headers: list[str], requested: str) -> int:
        try:
            return headers.index(requested)
        except ValueError as error:
            raise TargetResolutionError(
                f"table does not contain column {requested!r}"
            ) from error

    @staticmethod
    def _handle(target: ResolvedTarget) -> Locator:
        if target.handle is None:
            raise TargetResolutionError(
                f"target {target.target_ref!r} is absent"
            )
        return target.handle
