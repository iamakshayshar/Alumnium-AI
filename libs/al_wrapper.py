# libs/al_wrapper.py
import time
import logging
from typing import Any

logger = logging.getLogger("framework.alumnium")

class AlumniWrapper:
    """
    Wrap an Alumni instance to add:
      - retries when the model returns None or an unusable response
      - total timeout for the entire call
      - exponential backoff between retries (base = retry_backoff)
    """

    def __init__(self, alumni, timeout_seconds: int = 60, max_retries: int = 3, retry_backoff: float = 5.0, rp_logger=None):
        self._alumni = alumni
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.retry_backoff = float(retry_backoff)
        self.rp_logger = rp_logger or logger

    def _log(self, level, msg, *args, **kwargs):
        try:
            if self.rp_logger:
                # rp_logger can be RPLogger or standard logger
                getattr(self.rp_logger, level)(msg, *args, **kwargs)
        except Exception:
            # fallback to module logger
            getattr(logger, level)(msg, *args, **kwargs)

    def _is_usable_response(self, res: Any) -> bool:
        """
        Heuristics to decide whether res is usable:
         - not None
         - has some textual content via .content, .text, .message, 'choices', or is str/int/float
        """
        if res is None:
            return False
        # direct primitive results
        if isinstance(res, (str, bytes, int, float, bool)):
            return True
        # check common attributes that carriers of content expose
        for attr in ("content", "text", "message", "choices"):
            try:
                val = getattr(res, attr, None)
            except Exception:
                val = None
            if val:
                return True
        # otherwise be conservative and consider it usable if it's not explicitly falsy
        return True

    def _call_with_retries(self, method_name: str, *args, **kwargs):
        start = time.monotonic()
        attempt = 0
        backoff = float(self.retry_backoff)

        while True:
            attempt += 1
            elapsed = time.monotonic() - start
            if elapsed > self.timeout_seconds:
                self._log("error", "Alumnium wrapper: total timeout %ss exceeded after %d attempts", self.timeout_seconds, attempt-1)
                raise TimeoutError(f"Alumnium call exceeded total timeout of {self.timeout_seconds} seconds")

            try:
                self._log("debug", "Alumnium wrapper: attempt %d for %s", attempt, method_name)
                method = getattr(self._alumni, method_name)
                res = method(*args, **kwargs)
            except Exception as exc:
                self._log("warning", "Alumnium wrapper: exception on attempt %d: %s", attempt, exc)
                if attempt >= self.max_retries:
                    self._log("error", "Alumnium wrapper: exhausted retries (%d) for %s due to exceptions", self.max_retries, method_name)
                    raise
                # sleep then retry (exponential backoff)
                time.sleep(backoff)
                backoff *= 2
                continue

            # If result is unusable (None or missing content), retry
            if not self._is_usable_response(res):
                self._log("warning", "Alumnium wrapper: unusable (None/empty) response on attempt %d for %s", attempt, method_name)
                if attempt >= self.max_retries:
                    self._log("error", "Alumnium wrapper: exhausted retries (%d) for %s; last result unusable", self.max_retries, method_name)
                    raise RuntimeError(f"Alumnium returned unusable response after {self.max_retries} attempts")
                time.sleep(backoff)
                backoff *= 2
                continue

            # Good response — return it
            return res

    # convenience methods — proxy commonly used calls
    def do(self, *args, **kwargs):
        return self._call_with_retries("do", *args, **kwargs)

    def check(self, *args, **kwargs):
        return self._call_with_retries("check", *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._call_with_retries("get", *args, **kwargs)

    # generic proxy: allows direct attribute access for other Alumni methods
    def __getattr__(self, name):
        # If a direct method exists on Alumni, return a wrapper that will call it with retries.
        if hasattr(self._alumni, name):
            def _method(*args, **kwargs):
                return self._call_with_retries(name, *args, **kwargs)
            return _method
        raise AttributeError(name)
