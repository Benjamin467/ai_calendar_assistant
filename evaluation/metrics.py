"""Small, dependency-free metric helpers."""
from difflib import SequenceMatcher
from statistics import mean
from typing import Iterable, List


def rate(flags: Iterable[bool]) -> float:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else float("nan")


def avg(values: List[float]) -> float:
    return mean(values) if values else float("nan")


def title_match(pred: str, gold: str, threshold: float = 0.8) -> bool:
    p, g = pred.lower().strip(), gold.lower().strip()
    if not g:
        return not p
    return p == g or SequenceMatcher(None, p, g).ratio() >= threshold


def pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.1f}%"
