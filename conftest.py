# conftest.py
import os
import configparser
import pytest
import logging
from pathlib import Path
from typing import Dict
import time
import logging
from typing import Any

from utils.driver_factory import create_selenium_driver
from libs.common import screenshot_bytes_from_selenium

# Path to config.ini (adjust if you keep config elsewhere)
CONFIG_PATH = Path(__file__).parent / "config.ini"

logger = logging.getLogger("framework.alumnium_patch")

def patch_alumnium_planner_invoke(max_retries: int = 3, retry_backoff: float = 5.0, total_timeout: float = 60.0):
    """
    Monkey-patch Alumnium's PlannerAgent.invoke to retry when the underlying
    _invoke_chain returns None (or otherwise malformed message) which would
    otherwise cause AttributeError on message.content.
    """
    try:
        # import the PlannerAgent class from the installed package
        from alumnium.server.agents.planner_agent import PlannerAgent
    except Exception as exc:
        logger.debug("Could not import PlannerAgent to patch it: %s", exc)
        return

    # keep original for fallback
    original_invoke = getattr(PlannerAgent, "invoke", None)
    if original_invoke is None:
        logger.debug("PlannerAgent.invoke not found; nothing to patch.")
        return

    def safe_invoke(self, goal: str, accessibility_tree_xml: str):
        """Wrapped invoke with retries and None-safety."""
        start = time.monotonic()
        attempt = 0
        backoff = float(retry_backoff)

        while True:
            attempt += 1
            elapsed = time.monotonic() - start
            if elapsed > float(total_timeout):
                msg = f"PlannerAgent.invoke: total timeout {total_timeout}s exceeded after {attempt-1} attempts"
                logger.error(msg)
                raise TimeoutError(msg)

            try:
                # call original _invoke_chain logic through the original method body
                message = original_invoke(self, goal, accessibility_tree_xml)
            except Exception as exc:
                logger.warning("PlannerAgent.invoke attempt %d raised: %s", attempt, exc, exc_info=True)
                if attempt >= int(max_retries):
                    logger.error("PlannerAgent.invoke exhausted retries (%d) after exception", max_retries)
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue

            # if the original returns None (or a falsy message), retry
            if message is None:
                logger.warning("PlannerAgent.invoke attempt %d returned None for goal=%r — retrying", attempt, goal)
                if attempt >= int(max_retries):
                    raise RuntimeError(f"PlannerAgent.invoke returned None after {max_retries} attempts for goal: {goal}")
                time.sleep(backoff)
                backoff *= 2
                continue

            # Defensive: if message lacks expected fields, try to recover or fail with clear error
            # Some code paths expect message.content or message['parsed']
            try:
                # if message is dict-like and has 'parsed' or 'content', return as-is
                if isinstance(message, dict) or hasattr(message, "__getitem__"):
                    return message
                # if it has content attribute, return it (normal case)
                if hasattr(message, "content") or hasattr(message, "parsed") or hasattr(message, "raw"):
                    return message
            except Exception:
                # fall-through to returning message if it looks non-None
                return message

            # fallback - return message
            return message

    # install the wrapper
    setattr(PlannerAgent, "invoke", safe_invoke)
    logger.info("Patched Alumnium PlannerAgent.invoke to be None-safe with retries: max_retries=%s backoff=%s total_timeout=%s",
                max_retries, retry_backoff, total_timeout)

def _apply_llm_config_from_cfg(cfg: configparser.ConfigParser, section_name: str = "llm") -> Dict[str, str]:
    """
    Read the [llm] section from config.ini and set the env vars Alumnium expects.
    Supported provider: 'ollama'. Sets:
      - ALUMNIUM_MODEL = "ollama"
      - ALUMNIUM_OLLAMA_URL = <ollama_url> (if provided)
      - ALUMNIUM_OLLAMA_MODEL = <model> (optional)
    Returns the dict of llm values read (may be empty).
    """
    if section_name not in cfg:
        return {}

    llm_cfg = dict(cfg[section_name])
    provider = llm_cfg.get("provider", "").strip().lower()
    ollama_url = llm_cfg.get("ollama_url", "").strip()
    model = llm_cfg.get("model", "").strip()

    if provider == "ollama":
        os.environ.setdefault("ALUMNIUM_MODEL", "ollama")
        if ollama_url:
            os.environ.setdefault("ALUMNIUM_OLLAMA_URL", ollama_url)
        if model:
            os.environ.setdefault("ALUMNIUM_OLLAMA_MODEL", model)
    else:
        # Generic fallback mapping
        if provider:
            os.environ.setdefault("ALUMNIUM_MODEL", provider)
        if model:
            os.environ.setdefault("ALUMNIUM_MODEL_NAME", model)

    # non-secret flag for diagnostics
    os.environ.setdefault("ALUMNIUM_LLM_CONFIGURED", "true" if provider else "false")
    return llm_cfg


@pytest.fixture(scope="session")
def config():
    """
    Load config.ini, apply LLM config early (so env vars are present prior to Alumnium import),
    and return a merged dict of DEFAULT + chosen environment section.
    """
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    # Apply LLM config BEFORE anything that may import Alumnium runs.
    llm_config = _apply_llm_config_from_cfg(cfg, section_name="llm")

    env = os.getenv("ENV", cfg["DEFAULT"].get("environment", "local"))
    env_cfg = dict(cfg["DEFAULT"])
    if env in cfg:
        env_cfg.update(dict(cfg[env]))

    # Normalise types and include llm sub-dict
    env_cfg["headless"] = str(env_cfg.get("headless", "true")).lower() == "true"
    env_cfg["implicit_wait"] = int(env_cfg.get("implicit_wait", 5))
    # Optional robustness params (defaults)
    env_cfg["timeout_seconds"] = int(env_cfg.get("timeout_seconds", 60))
    env_cfg["max_retries"] = int(env_cfg.get("max_retries", 3))
    env_cfg["retry_backoff"] = float(env_cfg.get("retry_backoff", 5))
    env_cfg["llm"] = llm_config

    # inside your config() fixture in conftest.py, after reading CONFIG_PATH and applying llm env vars:
    llm_cfg = _apply_llm_config_from_cfg(cfg, section_name="llm")
    # read robustness settings (defaults if missing)
    max_retries = int(cfg["DEFAULT"].get("max_retries", 3))
    retry_backoff = float(cfg["DEFAULT"].get("retry_backoff", 5))
    timeout_seconds = float(cfg["DEFAULT"].get("timeout_seconds", 60))


    patch_alumnium_planner_invoke(max_retries=max_retries, retry_backoff=retry_backoff, total_timeout=timeout_seconds)

    return env_cfg


@pytest.fixture(scope="session")
def driver(config):
    """Create a Selenium driver for the session and yield it."""
    headless = config.get("headless", True)
    implicit_wait = config.get("implicit_wait", 5)
    _, drv, cleanup = create_selenium_driver(headless=headless, implicit_wait=implicit_wait)
    yield drv
    try:
        cleanup()
    except Exception:
        pass


# ReportPortal logger setup (best effort). Uses pytest-reportportal RPLogger if available.
try:
    from pytest_reportportal import RPLogger, RPLogHandler
except Exception:
    RPLogger = None
    RPLogHandler = None


@pytest.fixture(scope="session")
def rp_logger(request):
    """
    Returns a logger that writes to ReportPortal if plugin available, otherwise a standard logger.
    """
    if RPLogger is None:
        # fallback: basic StdOut logger
        logger = logging.getLogger("framework")
        if not logger.handlers:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            logger.addHandler(ch)
        return logger

    logging.setLoggerClass(RPLogger)
    logger = logging.getLogger("framework")
    logger.setLevel(logging.DEBUG)
    rp_handler = RPLogHandler(request.node.config.py_test_service)
    logger.addHandler(rp_handler)
    return logger


# Wrap Alumni with the robust wrapper (retries / timeout / backoff)
@pytest.fixture(scope="session")
def al(driver, config, rp_logger):
    """
    Initialize Alumnium Alumni instance bound to Selenium driver, and wrap it with AlumniWrapper
    to add retries / timeout / backoff behavior. Requires libs/al_wrapper.py to be present.
    """
    # Import here so LLM env vars (set in config()) are applied before Alumnium import.
    try:
        from alumnium import Alumni
    except Exception as exc:
        # Re-raise with clearer guidance
        raise RuntimeError(
            "Failed to import `alumnium`. Ensure the package is installed and package data (prompts) are present. "
            "Try: pip install --no-cache-dir --force-reinstall alumnium"
        ) from exc

    # instantiate raw alumni
    alumni = Alumni(driver)

    # import wrapper (local implementation)
    try:
        from libs.al_wrapper import AlumniWrapper
    except Exception as exc:
        raise RuntimeError(
            "Missing libs.al_wrapper; please add libs/al_wrapper.py (the AlumniWrapper implementation)."
        ) from exc

    # read robustness params from config
    timeout_seconds = int(config.get("timeout_seconds", 60))
    max_retries = int(config.get("max_retries", 3))
    retry_backoff = float(config.get("retry_backoff", 5))

    wrapper = AlumniWrapper(
        alumni,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        rp_logger=rp_logger,
    )
    return wrapper


# Attach screenshot to ReportPortal when test fails (if plugin is active)
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    On test failure during the 'call' phase, capture a Selenium screenshot and post to ReportPortal
    (if pytest-reportportal plugin exposed py_test_service on the config).
    """
    outcome = yield
    rep = outcome.get_result()

    if rep.when == "call" and rep.failed:
        driver_fixture = item.funcargs.get("driver")
        if driver_fixture:
            try:
                data = screenshot_bytes_from_selenium(driver_fixture)
                rp_service = getattr(item.config, "py_test_service", None)
                if rp_service:
                    rp_service.post_log(
                        item.name,
                        "ERROR",
                        message="Failure screenshot",
                        attachment={"name": "screenshot.png", "data": data},
                    )
            except Exception:
                # Never fail the test run because screenshot logic failed
                logging.getLogger("framework").exception("Failed to capture/post screenshot for failed test.")
