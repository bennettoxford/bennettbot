import functools
import inspect

import structlog

# Configure structlog to write to stdout without timstamps.
structlog.configure(processors=[structlog.dev.ConsoleRenderer()])
logger = structlog.get_logger()


def log_call(fn):
    """Decorate fn to log its arguments and return value each time it's called."""

    spec = inspect.getfullargspec(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        params = dict(zip(spec.args, args))
        params.update(kwargs)

        logger.info(fn.__name__ + " {")
        if params:
            logger.info(fn.__name__, **params)

        rv = fn(*args, **kwargs)

        if rv:
            logger.info(fn.__name__, rv=rv)

        logger.info(fn.__name__ + " }")

        return rv

    return wrapper
