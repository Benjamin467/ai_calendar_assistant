"""Text normalisation. We deliberately KEEP digits, colons, slashes and case
information because they are essential for date/time extraction."""
import re
import unicodedata

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30,
}
_UNITS = r"(?:minutes?|mins?|hours?|hrs?|days?|weeks?)"
_NUMWORD_RE = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r")\s+(?=" + _UNITS + r"\b)", re.IGNORECASE)


def normalize(text: str) -> str:
    """Unicode-normalise, unify quotes and collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", text).strip()


def number_words_to_digits(text: str) -> str:
    """'one day before' -> '1 day before' (only when followed by a time unit)."""
    return _NUMWORD_RE.sub(lambda m: f"{_NUMBER_WORDS[m.group(1).lower()]} ", text)


def preprocess(text: str) -> str:
    return number_words_to_digits(normalize(text))
