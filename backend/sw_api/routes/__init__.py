"""Phase B routes, registered on the app by create_app (they share its auth dependencies)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Deps:
    """What every route module needs from create_app."""

    runtime: Any
    user: Callable  # dependency: any logged-in person
    roles: Callable[..., Callable]  # roles("it", "admin") -> dependency
    require_bed: Callable[[str], None]
