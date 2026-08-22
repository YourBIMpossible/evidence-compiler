"""Golden-fixture module: defines AlphaService and compute_alpha."""


class AlphaService:
    """A service the fixture prompts will ask about by name."""

    def __init__(self, factor: int = 2) -> None:
        self.factor = factor

    def run(self, value: int) -> int:
        return compute_alpha(value) * self.factor


def compute_alpha(value: int) -> int:
    """Return a deterministic transform of ``value``."""
    return (value * 3) + 1
