"""Suppress vnstock's promotional banners (vnai.scope.promo).

Import this module before touching vnstock. It monkey-patches ContentManager
to no-op. Safe to call repeatedly.
"""

from __future__ import annotations

_patched = False


def silence() -> None:
    global _patched
    if _patched:
        return
    try:
        from vnai.scope import promo  # type: ignore

        def _noop(self, *args, **kwargs):
            return None

        promo.ContentManager.present_content = _noop  # type: ignore[attr-defined]
        promo.ContentManager.show_startup_ad = lambda self: False  # type: ignore[attr-defined]
        _patched = True
    except Exception:  # noqa: BLE001
        # Best-effort: ignore if vnai layout changes.
        pass


silence()
