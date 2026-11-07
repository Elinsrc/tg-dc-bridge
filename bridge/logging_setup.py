# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import inspect
import logging
import platform
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class LoggingSetup:
    QUIET = ("hydrogram.syncer", "hydrogram.client", "discord.gateway", "discord.http")
    FORMAT = (
        "[<green>{time:YYYY-MM-DD HH:mm:ss}</green>] "
        "[<level>{level}</level>] "
        "<white>{name}</white>.<white>{function}</white>: "
        "<level>{message}</level>"
    )

    def __init__(self, level: str):
        self.level = level

    def configure(self) -> None:
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
        for name in self.QUIET:
            logging.getLogger(name).setLevel(logging.WARNING)
        logger.remove()
        logger.add(sys.stdout, format=self.FORMAT, level=self.level, colorize=True)

    @staticmethod
    def install_uvloop() -> None:
        try:
            import uvloop

            uvloop.install()
        except ImportError:
            if platform.system() != "Windows":
                logger.warning("uvloop is not installed and therefore will be disabled.")
