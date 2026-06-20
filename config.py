import warnings
import logging

# Suppress a LangGraph internal deprecation warning about JsonPlusSerializer defaults
warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]