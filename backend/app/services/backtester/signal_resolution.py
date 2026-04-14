import asyncio
import inspect
import threading
from typing import Any


def resolve_signal_output(signal_output: Any) -> Any:
    if not inspect.isawaitable(signal_output):
        return signal_output

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(signal_output)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(signal_output)
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]

    return result.get("value")
