from __future__ import annotations

from typing import assert_never

from understudy.artifact.models import (
    Action,
    ActivateAction,
    EnterTextAction,
    NavigateAction,
    PressKeyAction,
    ReadAction,
    RouteDefinition,
    Target,
)
from understudy.replay.context import ReplayContext
from understudy.replay.parsers import parse_money
from understudy.surface import ResolvedTarget, Surface


class ActionExecutor:
    def __init__(
        self,
        surface: Surface,
        targets: dict[str, Target],
        routes: dict[str, RouteDefinition],
    ) -> None:
        self._surface = surface
        self._targets = targets
        self._routes = routes

    def execute(
        self,
        action: Action,
        context: ReplayContext,
    ) -> None:
        if isinstance(action, NavigateAction):
            route = self._routes[action.route_ref]
            url = context.render(route.pattern)
            self._surface.navigate(url)
            return

        if isinstance(action, EnterTextAction):
            target = self._resolve(action.target_ref, context)
            value = str(context.lookup(action.value_from))
            self._surface.enter_text(target, value)
            return

        if isinstance(action, ActivateAction):
            target = self._resolve(action.target_ref, context)
            self._surface.activate(target)
            return

        if isinstance(action, ReadAction):
            target = self._resolve(action.target_ref, context)
            text = self._surface.read_text(target)

            parsed = parse_money(
                text,
                locale=action.parser.locale,
                expected_currency=(
                    action.parser.expected_currency
                ),
            )

            context.outputs[action.parser.amount_output] = (
                parsed.amount_cents
            )
            context.outputs[action.parser.currency_output] = (
                parsed.currency
            )
            return

        if isinstance(action, PressKeyAction):
            target: ResolvedTarget | None = None

            if action.target_ref is not None:
                target = self._resolve(
                    action.target_ref,
                    context,
                )

            self._surface.press_key(action.key, target)
            return

        assert_never(action)

    def _resolve(
        self,
        target_ref: str,
        context: ReplayContext,
    ) -> ResolvedTarget:
        return self._surface.resolve_target(
            target_ref,
            self._targets[target_ref],
            context.values(),
        )