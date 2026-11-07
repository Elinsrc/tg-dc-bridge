# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio

from bridge.app import BridgeApp
from bridge.logging_setup import LoggingSetup
from bridge.settings import Settings

if __name__ == "__main__":
    settings = Settings.load()
    LoggingSetup(settings.log_level).configure()
    LoggingSetup.install_uvloop()
    asyncio.run(BridgeApp(settings).run())
