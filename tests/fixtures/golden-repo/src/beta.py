"""Golden-fixture module: consumes AlphaService (a lexical reference site)."""

from .alpha import AlphaService


def build_service() -> AlphaService:
    # AlphaService referenced here so ripgrep finds a def + a reference.
    return AlphaService(factor=4)


def total(values: list[int]) -> int:
    service = build_service()
    return sum(service.run(v) for v in values)
