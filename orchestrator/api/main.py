# CRITICAL: Load environment variables FIRST before any other imports
from dotenv import load_dotenv

load_dotenv()

# CRITICAL: Add orchestrator directory to sys.path BEFORE any other imports
# This ensures that imports like "from utils.json_utils" work correctly
import os  # noqa: F401
import sys
from pathlib import Path

orchestrator_dir = Path(__file__).resolve().parent.parent
if str(orchestrator_dir) not in sys.path:
    sys.path.insert(0, str(orchestrator_dir))

from logging_config import get_logger, setup_logging

from . import (
    agent_facade_support,
    main_app_wiring_facade_support,
    main_route_module_facade_support,
    main_runtime_dependency_facade_support,
    main_static_facade_support,
    main_test_lifecycle_facade_support,
)

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

main_runtime_dependency_facade_support.configure_main_runtime_dependency_facade(globals())
main_static_facade_support.configure_main_static_facade(globals())
main_route_module_facade_support.configure_main_route_module_facade(globals())
main_app_wiring_facade_support.configure_main_app_wiring_facade(globals())
app = globals()["app"]
main_test_lifecycle_facade_support.configure_main_test_lifecycle_facade(globals())


def _agent_compat_runtime():
    return sys.modules[__name__]


agent_facade_support.configure_agent_facade(_agent_compat_runtime, globals())
