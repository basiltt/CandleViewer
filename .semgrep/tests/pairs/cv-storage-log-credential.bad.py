import logging
logger = logging.getLogger(__name__)
def f(dsn):
    logger.info(f"using {dsn}")
