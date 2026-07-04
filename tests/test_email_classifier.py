"""Unit tests for EmailClassifier."""
from unittest.mock import MagicMock

import pytest

from src.email_classifier import EmailClassification, EmailClassifier


@pytest.fixture
def classifier():
    model = MagicMock()
    model.with_structured_output.return_value = MagicMock()
    c = EmailClassifier(model=model)
    # Replace the LCEL RunnableSequence with a plain MagicMock so we can
    # control invoke() return values without going through the real chain.
    c._chain = MagicMock()
    return c


def _stub_result(classifier, **kwargs):
    """Make the chain return a fake EmailClassification with given fields."""
    defaults = dict(
        intent="meeting_request", confidence=0.9,
        raw_date="next Monday", start_raw_time="10:00", end_raw_time="",
        language="English",
    )
    defaults.update(kwargs)
    classifier._chain.invoke.return_value = EmailClassification(**defaults)


def test_analyze_email_returns_dict(classifier):
    _stub_result(classifier)
    result = classifier.analyze_email("Meeting", "alice@x.com", "Can we meet?")
    assert isinstance(result, dict)


def test_analyze_email_passes_fields_to_chain(classifier):
    _stub_result(classifier)
    classifier.analyze_email("Subject", "sender@x.com", "Body text")
    classifier._chain.invoke.assert_called_once_with(
        {"subject": "Subject", "sender": "sender@x.com", "body": "Body text"}
    )


def test_analyze_email_returns_all_expected_keys(classifier):
    _stub_result(classifier)
    result = classifier.analyze_email("S", "s@x.com", "B")
    assert set(result.keys()) == {"intent", "confidence", "raw_date", "start_raw_time", "end_raw_time", "language"}


def test_analyze_email_meeting_request_intent(classifier):
    _stub_result(classifier, intent="meeting_request", raw_date="next Friday", start_raw_time="14h")
    result = classifier.analyze_email("Meeting", "a@b.com", "Let's meet next Friday at 14h")
    assert result["intent"] == "meeting_request"
    assert result["raw_date"] == "next Friday"
    assert result["start_raw_time"] == "14h"


def test_analyze_email_other_intent_empty_date(classifier):
    _stub_result(classifier, intent="other", raw_date="", start_raw_time="", language="French")
    result = classifier.analyze_email("Hello", "a@b.com", "Comment vas-tu?")
    assert result["intent"] == "other"
    assert result["raw_date"] == ""
    assert result["language"] == "French"
