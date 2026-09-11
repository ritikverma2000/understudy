from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Locator, Page

from understudy.discovery.models import ControlSnapshot, Observation


@dataclass(frozen=True)
class LiveControl:
    snapshot: ControlSnapshot
    locator: Locator


class PlaywrightDiscoverySurface:
    selector = "h1, h2, h3, input, textarea, select, button, a, table, tbody td"

    def __init__(self, page: Page) -> None:
        self.page = page
        self._controls: dict[str, LiveControl] = {}

    def navigate(self, url: str) -> None:
        self.page.goto(url)

    def observe(self) -> Observation:
        controls: list[ControlSnapshot] = []
        live: dict[str, LiveControl] = {}
        control_index = 1

        for frame_index, frame in enumerate(self.page.frames):
            candidates = frame.locator(self.selector)

            for index in range(candidates.count()):
                locator = candidates.nth(index)
                if not locator.is_visible():
                    continue

                metadata = locator.evaluate(
                    """element => {
                      const tag = element.tagName.toLowerCase();
                      const labels = element.labels
                        ? Array.from(element.labels).map(
                            label => label.innerText.trim()
                          )
                        : [];
                      const caption = tag === 'table'
                        ? element.querySelector('caption')?.innerText.trim()
                        : '';
                      const role = element.getAttribute('role') || ({
                        h1: 'heading', h2: 'heading', h3: 'heading',
                        input: element.type === 'submit' ? 'button' : 'textbox',
                        textarea: 'textbox', select: 'combobox', button: 'button',
                        a: 'link', table: 'table', td: 'cell'
                      }[tag] || tag);
                      const name = labels.join(' ') || caption ||
                        element.getAttribute('aria-label') ||
                        element.innerText || element.getAttribute('name') || '';
                      return {role, name: name.trim().replace(/\\s+/g, ' ')};
                    }"""
                )
                name = str(metadata["name"])[:160]
                if not name:
                    continue

                control_id = f"c{control_index}"
                snapshot = ControlSnapshot(
                    id=control_id,
                    role=str(metadata["role"]),
                    name=name,
                    context=f"frame:{frame_index}",
                )
                controls.append(snapshot)
                live[control_id] = LiveControl(snapshot, locator)
                control_index += 1

        self._controls = live
        return Observation(
            url=self.page.url,
            title=self.page.title(),
            controls=controls,
        )

    def control(self, control_id: str) -> LiveControl:
        try:
            return self._controls[control_id]
        except KeyError as error:
            raise ValueError(f"unknown observed control {control_id!r}") from error

    def type_text(self, control_id: str, value: str) -> LiveControl:
        control = self.control(control_id)
        control.locator.fill(value)
        return control

    def activate(self, control_id: str) -> LiveControl:
        control = self.control(control_id)
        control.locator.click()
        self.page.wait_for_timeout(200)
        return control

    def read(self, control_id: str) -> tuple[LiveControl, str]:
        control = self.control(control_id)
        return control, control.locator.inner_text().strip()
