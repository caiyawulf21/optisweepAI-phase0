"""Deterministic keyword + negation-aware symptom & component extractor.

Loads phrase tables (Cosmos gate_phrase_table at runtime, YAML fallback) and
maps operator free text onto symptom keys and components. Symptom keys are
whatever the published vocabulary contains — not a fixed CAT taxonomy.
Root-cause / category labeling is out of scope for this extractor.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_SIGNAL_PHRASES_PATH = (
    Path(__file__).resolve().parent / "symptom_extraction_phrases.yaml"
)
DEFAULT_COMPONENT_PHRASES_PATH = (
    Path(__file__).resolve().parent / "symptom_components_phrases.yaml"
)
DEFAULT_CANONICAL_SIGNAL_PHRASES_PATH = (
    Path(__file__).resolve().parent / "canonical_signal_phrases.yaml"
)


_NEGATION_TOKENS: tuple[str, ...] = (
    r"\bno\s+longer\b",
    r"\bnever\b",
    r"\bnot\b",
    r"\bno\b",
    r"\bwithout\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bdoesn't\b",
    r"\bdidn't\b",
    r"\bwon't\b",
    r"\bisn't\b",
    r"\baren't\b",
)
_NEGATION_RE = re.compile("|".join(_NEGATION_TOKENS), re.IGNORECASE)
_NEGATION_WINDOW_TOKENS = 4
_HARD_BOUNDARY_RE = re.compile(r"[.;!?,]")
_ABSENCE_AFFIRMATIVE_SIGNAL_KEYS = frozenset({"no_rms_alarm"})
_ABSENCE_AFFIRMATIVE_CANONICAL_KEYS = frozenset({"rms_screen_no_faults_visible"})
_CONTRACTION_RE = re.compile(
    r"\b(aren't|arent|isn'?t|isnt|wasn'?t|wasnt|weren'?t|werent|don'?t|dont|"
    r"doesn'?t|doesnt|didn'?t|didnt|won'?t|wont|can'?t|cant|cannot|"
    r"couldn'?t|couldnt|shouldn'?t|shouldnt|wouldn'?t|wouldnt)\b",
    re.IGNORECASE,
)
_CONTRACTION_MAP = {
    "aren't": "are not",
    "arent": "are not",
    "isnt": "is not",
    "isn't": "is not",
    "wasnt": "was not",
    "wasn't": "was not",
    "werent": "were not",
    "weren't": "were not",
    "dont": "do not",
    "don't": "do not",
    "doesnt": "does not",
    "doesn't": "does not",
    "didnt": "did not",
    "didn't": "did not",
    "wont": "will not",
    "won't": "will not",
    "cant": "cannot",
    "can't": "cannot",
    "cannot": "cannot",
    "couldnt": "could not",
    "couldn't": "could not",
    "shouldnt": "should not",
    "shouldn't": "should not",
    "wouldnt": "would not",
    "wouldn't": "would not",
}


def _normalize_operator_text(user_message: str) -> str:
    """Lowercase and expand common contractions before phrase matching."""
    text = (user_message or "").lower().strip()
    if not text:
        return ""
    # Normalize curly apostrophes from chat UIs.
    text = text.replace("\u2019", "'").replace("\u2018", "'")

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0).lower()
        return _CONTRACTION_MAP.get(raw, _CONTRACTION_MAP.get(raw.replace("'", ""), raw))

    return _CONTRACTION_RE.sub(repl, text)


@dataclass
class ExtractionResult:
    """Output of :meth:`KeywordSignalExtractor.extract`.

    ``signals`` holds every symptom key in the active phrase vocabulary for
    this extractor (True/False). ``observed_signals`` is the subset that
    actually matched this turn (affirmative or explicit negation).
    ``canonical_signals`` holds mid-flow / procedure-oriented keys from the
    canonical phrase table when they fire. ``components`` is equipment /
    area vocabulary for overlap scoring.
    """

    signals: dict[str, bool] = field(default_factory=dict)
    observed_signals: dict[str, bool] = field(default_factory=dict)
    canonical_signals: dict[str, bool] = field(default_factory=dict)
    negated_signals: set[str] = field(default_factory=set)
    components: set[str] = field(default_factory=set)
    matched_phrases: dict[str, list[str]] = field(default_factory=dict)


class KeywordSignalExtractor:
    """Class-based keyword extractor with negation handling.

    The extractor is stateless after construction. Tests can build a
    custom extractor via :meth:`from_phrases` to pin behaviour without
    touching the YAML file.
    """

    def __init__(
        self,
        *,
        signal_phrases: Mapping[str, Iterable[str]],
        component_phrases: Mapping[str, Iterable[str]] | None = None,
        canonical_signal_phrases: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._signal_phrases: dict[str, tuple[str, ...]] = {
            key: tuple(p.lower() for p in (phrases or ()))
            for key, phrases in signal_phrases.items()
        }
        self._component_phrases: dict[str, tuple[str, ...]] = {
            key: tuple(p.lower() for p in (phrases or ()))
            for key, phrases in (component_phrases or {}).items()
        }
        self._canonical_signal_phrases: dict[str, tuple[str, ...]] = {
            key: tuple(p.lower() for p in (phrases or ()))
            for key, phrases in (canonical_signal_phrases or {}).items()
        }

    @classmethod
    def from_files(
        cls,
        signal_phrases_path: Path | None = None,
        component_phrases_path: Path | None = None,
        canonical_signal_phrases_path: Path | None = None,
    ) -> "KeywordSignalExtractor":
        signal_path = signal_phrases_path or DEFAULT_SIGNAL_PHRASES_PATH
        component_path = component_phrases_path or DEFAULT_COMPONENT_PHRASES_PATH
        canonical_path = (
            canonical_signal_phrases_path or DEFAULT_CANONICAL_SIGNAL_PHRASES_PATH
        )
        signal_phrases = _load_phrase_yaml(signal_path)
        component_phrases = (
            _load_phrase_yaml(component_path) if component_path.exists() else {}
        )
        canonical_signal_phrases = (
            _load_phrase_yaml(canonical_path) if canonical_path.exists() else {}
        )
        return cls(
            signal_phrases=signal_phrases,
            component_phrases=component_phrases,
            canonical_signal_phrases=canonical_signal_phrases,
        )

    @classmethod
    def from_phrases(
        cls,
        signal_phrases: Mapping[str, Iterable[str]],
        component_phrases: Mapping[str, Iterable[str]] | None = None,
        canonical_signal_phrases: Mapping[str, Iterable[str]] | None = None,
    ) -> "KeywordSignalExtractor":
        return cls(
            signal_phrases=signal_phrases,
            component_phrases=component_phrases,
            canonical_signal_phrases=canonical_signal_phrases,
        )

    @property
    def symptom_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._signal_phrases))

    def extract(self, user_message: str) -> ExtractionResult:
        text = _normalize_operator_text(user_message)
        signals: dict[str, bool] = {key: False for key in self._signal_phrases}
        observed_signals: dict[str, bool] = {}
        canonical_signals: dict[str, bool] = {}
        negated: set[str] = set()
        components: set[str] = set()
        matched_phrases: dict[str, list[str]] = {}
        if not text:
            return ExtractionResult(
                signals=signals,
                observed_signals=observed_signals,
                canonical_signals=canonical_signals,
                negated_signals=negated,
                components=components,
                matched_phrases=matched_phrases,
            )

        for signal_key, phrases in self._signal_phrases.items():
            absence_key = signal_key in _ABSENCE_AFFIRMATIVE_SIGNAL_KEYS
            for phrase in phrases:
                offset = text.find(phrase)
                if offset == -1:
                    continue
                if not absence_key and self._is_negated_at(text, offset):
                    if not signals.get(signal_key):
                        negated.add(signal_key)
                        observed_signals[signal_key] = False
                        matched_phrases.setdefault(signal_key, []).append(
                            f"!{phrase}"
                        )
                else:
                    signals[signal_key] = True
                    observed_signals[signal_key] = True
                    negated.discard(signal_key)
                    matched_phrases.setdefault(signal_key, []).append(phrase)

        for signal_key, phrases in self._canonical_signal_phrases.items():
            absence_key = signal_key in _ABSENCE_AFFIRMATIVE_CANONICAL_KEYS
            for phrase in phrases:
                offset = text.find(phrase)
                if offset == -1:
                    continue
                if not absence_key and self._is_negated_at(text, offset):
                    if not canonical_signals.get(signal_key):
                        canonical_signals[signal_key] = False
                        negated.add(signal_key)
                        matched_phrases.setdefault(signal_key, []).append(
                            f"!{phrase}"
                        )
                else:
                    canonical_signals[signal_key] = True
                    negated.discard(signal_key)
                    matched_phrases.setdefault(signal_key, []).append(phrase)

        if re.search(
            r"\b(escalate|need help from engineering|call engineer)\b", text
        ):
            signals["user_requests_escalation"] = True
            observed_signals["user_requests_escalation"] = True
            matched_phrases.setdefault("user_requests_escalation", []).append(
                "regex:escalate"
            )

        for component_key, phrases in self._component_phrases.items():
            for phrase in phrases:
                if phrase in text:
                    components.add(component_key)
                    break

        return ExtractionResult(
            signals=signals,
            observed_signals=observed_signals,
            canonical_signals=canonical_signals,
            negated_signals=negated,
            components=components,
            matched_phrases=matched_phrases,
        )

    def _is_negated_at(self, text: str, phrase_offset: int) -> bool:
        """Return True if a negation cue precedes ``phrase_offset`` within
        the negation window AND no hard sentence boundary sits between.

        We look at the last ``_NEGATION_WINDOW_TOKENS`` whitespace-delimited
        tokens immediately before the phrase. If any of them is a negation
        cue (``no``, ``not``, ``without``, ``never``, ``cannot``...) the
        phrase is treated as negated. A hard sentence boundary
        (``.;!?,``) between the negation cue and the phrase resets the
        scope so "AGVs are stopped. No RMS alarms." and
        "agvs aren't moving, rms showing no alarms" correctly mark
        only the intended clause, not sibling clauses.
        """
        if phrase_offset <= 0:
            return False
        before = text[:phrase_offset]
        boundary_match = None
        for m in _HARD_BOUNDARY_RE.finditer(before):
            boundary_match = m
        scope_start = boundary_match.end() if boundary_match else 0
        scope = before[scope_start:phrase_offset]
        tokens = scope.split()
        window = tokens[-_NEGATION_WINDOW_TOKENS:]
        if not window:
            return False
        scope_tail = " ".join(window)
        return bool(_NEGATION_RE.search(scope_tail))


def _load_phrase_yaml(path: Path) -> dict[str, list[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"Phrase YAML at {path} must be a mapping, got {type(raw).__name__}."
        )
    cleaned: dict[str, list[str]] = {}
    for key, phrases in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"Non-string phrase key in {path}: {key!r}")
        if phrases is None:
            cleaned[key] = []
            continue
        if not isinstance(phrases, list):
            raise ValueError(
                f"Phrase entries for {key!r} in {path} must be a list, got "
                f"{type(phrases).__name__}."
            )
        out: list[str] = []
        for p in phrases:
            if not isinstance(p, str):
                raise ValueError(
                    f"Non-string phrase under {key!r} in {path}: {p!r}"
                )
            out.append(p)
        cleaned[key] = out
    return cleaned


_singleton_lock = threading.Lock()
_extractor_singleton: KeywordSignalExtractor | None = None


def get_default_extractor() -> KeywordSignalExtractor:
    """Return the process-wide :class:`KeywordSignalExtractor` singleton."""
    global _extractor_singleton
    with _singleton_lock:
        if _extractor_singleton is None:
            _extractor_singleton = KeywordSignalExtractor.from_files()
        return _extractor_singleton


def reset_default_extractor() -> None:
    """Drop the cached extractor so the next call reloads phrase YAML."""
    global _extractor_singleton
    with _singleton_lock:
        _extractor_singleton = None


def set_default_extractor(extractor: KeywordSignalExtractor | None) -> None:
    """Inject a custom extractor as the process-wide singleton."""
    global _extractor_singleton
    with _singleton_lock:
        _extractor_singleton = extractor


def reset_for_tests() -> None:
    set_default_extractor(None)


__all__ = [
    "ExtractionResult",
    "KeywordSignalExtractor",
    "get_default_extractor",
    "reset_for_tests",
    "set_default_extractor",
]
