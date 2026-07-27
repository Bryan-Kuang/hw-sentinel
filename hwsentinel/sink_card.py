"""The alert card: a small borderless panel that slides in from the right edge.

Rounded corners come from a `-transparentcolor` key plus arc-and-rectangle shapes on
a Canvas. They are not antialiased; at a 10px radius that reads fine. If it ever looks
rough, the fix is a per-pixel-alpha layered window driven by UpdateLayeredWindow,
which is a lot more ctypes for a small gain.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .config import CardCfg
from .rules import Alert

# Transparency key: a colour nothing in the design uses, so no real pixel is punched out.
KEY_COLOUR = "#FF00FE"

SURFACE = "#FAF9F5"      # Claude cream
BORDER = "#E5E1D8"
TITLE_FG = "#191919"
DETAIL_FG = "#6B6B68"
ACCENT = {"warn": "#D97757", "critical": "#BF4D43"}

RADIUS = 10
BAR_W = 4
BAR_INSET_X = 16
BAR_INSET_Y = 18
PAD_X = BAR_INSET_X + BAR_W + 14


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, fill: str):
    """A true rounded rectangle: two overlapping bars plus four corner pieslices.

    The obvious `create_polygon(..., smooth=True)` trick is a spline *through* the
    corner points, so it pulls the edges inward and leaves seams against adjacent
    shapes. Arcs give the real geometry.
    """
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
    if r <= 0:
        return
    d = 2 * r
    for cx, cy, start in ((x1, y1, 90), (x2 - d, y1, 0), (x1, y2 - d, 180), (x2 - d, y2 - d, 270)):
        canvas.create_arc(
            cx, cy, cx + d, cy + d, start=start, extent=90,
            fill=fill, outline=fill, style=tk.PIESLICE,
        )


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


class _Card:
    def __init__(self, manager: "CardManager", alert: Alert) -> None:
        self.manager = manager
        self.key = alert.key
        cfg = manager.cfg
        self.w, self.h = cfg.width, cfg.height

        win = tk.Toplevel(manager.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY_COLOUR)
        win.attributes("-alpha", 0.97)
        win.configure(bg=KEY_COLOUR)
        self.win = win

        self.canvas = tk.Canvas(win, width=self.w, height=self.h, bg=KEY_COLOUR, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click)

        accent = ACCENT.get(alert.severity, ACCENT["warn"])
        # Two stacked rounded rects give a 1px hairline without stroking an outline
        # (a stroke would trace the spline, not the shape). The accent is an inset
        # pill rather than a flush edge bar, so nothing needs clipping.
        _round_rect(self.canvas, 0, 0, self.w, self.h, RADIUS, BORDER)
        _round_rect(self.canvas, 1, 1, self.w - 1, self.h - 1, RADIUS - 1, SURFACE)
        _round_rect(
            self.canvas, BAR_INSET_X, BAR_INSET_Y,
            BAR_INSET_X + BAR_W, self.h - BAR_INSET_Y, BAR_W / 2, accent,
        )

        self.title_id = self.canvas.create_text(
            PAD_X, self.h * 0.36, anchor="w", text=alert.title,
            font=("Segoe UI Semibold", 12), fill=TITLE_FG,
        )
        self.detail_id = self.canvas.create_text(
            PAD_X, self.h * 0.66, anchor="w", text=alert.detail,
            font=("Segoe UI", 9), fill=DETAIL_FG,
        )

        self.x_hidden = manager.screen_w
        self.x_target = manager.screen_w - self.w - cfg.margin_x
        self.y = 0
        self.x = float(self.x_hidden)
        self._anim: str | None = None
        win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{self.y}")

    def _on_click(self, _event) -> None:
        self.manager.snooze(self.key)

    def update_text(self, alert: Alert) -> None:
        self.canvas.itemconfigure(self.title_id, text=alert.title)
        self.canvas.itemconfigure(self.detail_id, text=alert.detail)

    def place(self, y: int) -> None:
        self.y = y
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{self.y}")

    def slide(self, to_x: float, on_done: Callable[[], None] | None = None) -> None:
        if self._anim:
            self.win.after_cancel(self._anim)
            self._anim = None
        start_x, dur = self.x, max(1, self.manager.cfg.slide_ms)
        steps = max(1, dur // 16)
        step = {"i": 0}

        def tick() -> None:
            step["i"] += 1
            t = min(1.0, step["i"] / steps)
            self.x = start_x + (to_x - start_x) * _ease_out_cubic(t)
            try:
                self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{self.y}")
            except tk.TclError:
                return
            if t < 1.0:
                self._anim = self.win.after(16, tick)
            else:
                self._anim = None
                if on_done:
                    on_done()

        tick()

    def show(self) -> None:
        self.slide(self.x_target)

    def dismiss(self) -> None:
        self.slide(self.x_hidden, self.destroy)

    def destroy(self) -> None:
        if self._anim:
            try:
                self.win.after_cancel(self._anim)
            except tk.TclError:
                pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class CardManager:
    """Reconciles the set of on-screen cards against the set of active alerts."""

    def __init__(self, cfg: CardCfg, root: tk.Tk, on_snooze: Callable[[str], None] | None = None) -> None:
        self.cfg = cfg
        self.root = root
        self.on_snooze = on_snooze
        self.cards: dict[str, _Card] = {}
        self.closing: set[str] = set()
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()

    def snooze(self, key: str) -> None:
        if self.on_snooze:
            self.on_snooze(key)
        self._remove(key)

    def update(self, alerts: list[Alert], suppressed: bool = False) -> None:
        if not self.cfg.enabled or suppressed:
            for key in list(self.cards):
                self._remove(key)
            return

        wanted = {a.key: a for a in alerts}
        for key in list(self.cards):
            if key not in wanted:
                self._remove(key)

        for alert in alerts:
            card = self.cards.get(alert.key)
            if card is None:
                self.closing.discard(alert.key)
                card = _Card(self, alert)
                self.cards[alert.key] = card
                self._layout()
                card.show()
            else:
                card.update_text(alert)
        self._layout()

    def _remove(self, key: str) -> None:
        card = self.cards.pop(key, None)
        if card:
            card.dismiss()
        self._layout()

    def _layout(self) -> None:
        gap, m = self.cfg.gap, self.cfg.margin_y
        cards = list(self.cards.values())
        total = sum(c.h for c in cards) + gap * max(0, len(cards) - 1)

        if self.cfg.position == "right-top":
            y = m
        elif self.cfg.position == "right-bottom":
            y = self.screen_h - m - total
        else:
            y = (self.screen_h - total) // 2

        for card in cards:
            card.place(int(y))
            y += card.h + gap

    def destroy_all(self) -> None:
        for card in self.cards.values():
            card.destroy()
        self.cards.clear()
