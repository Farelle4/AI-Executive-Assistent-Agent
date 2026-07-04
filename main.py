import argparse
import logging
import time

import config 
from src.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


def _parse_args():
    parser = argparse.ArgumentParser(description="Email AI Orchestrator")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pass then exit (default: continuous polling)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Polling interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def run(orchestrator: AgentOrchestrator, once: bool = False, interval: int = 300) -> None:
    """Polling loop — separated from arg parsing for testability."""
    while True:
        try:
            logger.info("Starting pass...")
            count = orchestrator.run_batch()
            logger.info("Pass complete — processed %d emails.", count)
            created = orchestrator.run_sent_batch()
            if created:
                logger.info("Sent batch: created %d calendar event(s).", created)
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down cleanly.")
            return
        except Exception as e:
            logger.error("Pass failed with unexpected error: %s", e, exc_info=True)
        if once:
            break
        logger.info("Next run in %ds.", interval)
        time.sleep(interval)


def main():
    args = _parse_args()

    if args.debug:
        logging.root.setLevel(logging.DEBUG)

    logger.info("Starting Email AI Orchestrator (once=%s, interval=%ds)", args.once, args.interval)
    orchestrator = AgentOrchestrator()
    run(orchestrator, once=args.once, interval=args.interval)


if __name__ == "__main__":
    main()
