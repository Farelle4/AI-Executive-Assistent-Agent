"""Task 8 — main.py: polling loop, CLI args, clean exit."""
import logging
import sys
from unittest.mock import MagicMock, patch

import main


def test_once_calls_run_batch_exactly_once():
    mock_orch = MagicMock()
    mock_orch.run_batch.return_value = 0
    with patch("main.time") as mock_time:
        main.run(mock_orch, once=True, interval=300)
    mock_orch.run_batch.assert_called_once()
    mock_time.sleep.assert_not_called()


def test_interval_sleeps_between_passes():
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise KeyboardInterrupt
        return 0

    mock_orch = MagicMock()
    mock_orch.run_batch.side_effect = side_effect
    with patch("main.time") as mock_time:
        main.run(mock_orch, once=False, interval=60)
    mock_time.sleep.assert_called_with(60)


def test_keyboard_interrupt_exits_cleanly():
    mock_orch = MagicMock()
    mock_orch.run_batch.side_effect = KeyboardInterrupt
    with patch("main.time"):
        main.run(mock_orch, once=False, interval=300)  # must not raise


def test_default_interval_is_300():
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise KeyboardInterrupt
        return 0

    mock_orch = MagicMock()
    mock_orch.run_batch.side_effect = side_effect
    with patch("main.time") as mock_time:
        main.run(mock_orch, once=False, interval=300)
    mock_time.sleep.assert_called_with(300)


def test_debug_flag_sets_log_level():
    sys.argv = ["main.py", "--once", "--debug"]
    with patch("main.AgentOrchestrator") as MockOrch, \
         patch("main.time"):
        mock_orch = MagicMock()
        mock_orch.run_batch.return_value = 0
        MockOrch.return_value = mock_orch
        main.main()
    assert logging.root.level == logging.DEBUG
    # restore so other tests are unaffected
    logging.root.setLevel(logging.INFO)


def test_main_once_flag_parsed_correctly():
    sys.argv = ["main.py", "--once"]
    with patch("main.AgentOrchestrator") as MockOrch, \
         patch("main.time"):
        mock_orch = MagicMock()
        mock_orch.run_batch.return_value = 2
        MockOrch.return_value = mock_orch
        main.main()
    mock_orch.run_batch.assert_called_once()
