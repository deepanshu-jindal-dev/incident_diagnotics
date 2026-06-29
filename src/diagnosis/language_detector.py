"""Language detection for incident text — Chain of Responsibility.

Each detector inspects the (already log-prefix-stripped) trace text and
either claims it for its language or defers to the next link in the
chain. Only Python is implemented today; the JS/Java/Go/Ruby links are
stubs that always defer, so the chain falls through to "unknown".

Public surface: `detect_language(text) -> str`.
"""

import re
from abc import ABC, abstractmethod
from typing import Optional


class _LanguageDetector(ABC):
    def __init__(self) -> None:
        self._next: Optional["_LanguageDetector"] = None

    def set_next(self, detector: "_LanguageDetector") -> "_LanguageDetector":
        self._next = detector
        return detector

    def detect(self, text: str) -> str:
        result = self._try_detect(text)
        if result:
            return result
        return self._next.detect(text) if self._next else "unknown"

    @abstractmethod
    def _try_detect(self, text: str) -> str:
        """Return language string if detected, empty string if not."""
        ...


class _PythonDetector(_LanguageDetector):
    def _try_detect(self, text: str) -> str:
        if "Traceback (most recent call last)" in text:
            return "python"
        if re.search(r'File\s+"[^"]+\.py",\s+line\s+\d+', text):
            return "python"
        return ""


class _JavaScriptDetector(_LanguageDetector):
    def _try_detect(self, text: str) -> str:
        return ""  # not yet implemented


class _JavaDetector(_LanguageDetector):
    def _try_detect(self, text: str) -> str:
        return ""  # not yet implemented


class _GoDetector(_LanguageDetector):
    def _try_detect(self, text: str) -> str:
        return ""  # not yet implemented


class _RubyDetector(_LanguageDetector):
    def _try_detect(self, text: str) -> str:
        return ""  # not yet implemented


# Build the chain once at module level.
_python_detector     = _PythonDetector()
_js_detector         = _JavaScriptDetector()
_java_detector       = _JavaDetector()
_go_detector         = _GoDetector()
_ruby_detector       = _RubyDetector()

_python_detector.set_next(_js_detector) \
                .set_next(_java_detector) \
                .set_next(_go_detector) \
                .set_next(_ruby_detector)

_DETECTOR_CHAIN = _python_detector


def detect_language(text: str) -> str:
    """Run the detector chain over `text`, returning a language string
    ("python" / "unknown" / ...)."""
    return _DETECTOR_CHAIN.detect(text)
