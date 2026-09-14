#!/usr/bin/env python3
from __future__ import annotations


def _inject_truststore() -> None:
    try:
        import truststore
    except ImportError:
        return

    truststore.inject_into_ssl()


def main() -> None:
    _inject_truststore()

    from notebooklm_tools.cli.main import app

    app()


if __name__ == "__main__":
    main()
