"""Allow running as `python -m temple`."""

from temple.config import settings


def main() -> None:
    """Dispatch to combined, MCP, or REST runtime based on configuration."""
    if settings.runtime_mode == "rest":
        from temple.rest_server import main as rest_main

        rest_main()
        return
    if settings.runtime_mode == "combined":
        from temple.combined_server import main as combined_main

        combined_main()
        return

    from temple.server import main as mcp_main

    mcp_main()


main()
