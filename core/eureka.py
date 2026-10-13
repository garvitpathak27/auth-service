import atexit
import logging
import signal
import threading

from django.conf import settings
from py_eureka_client import eureka_client


logger = logging.getLogger(__name__)
_registration_lock = threading.RLock() # this is to lock the eureka registration so that there are no race condition 
_registration_started = False
_shutdown_hooks_installed = False


def _build_registration_kwargs():
    """ prepare the information to send to the eureka """
    return {
        "eureka_server": settings.EUREKA_SERVER_URL,
        "app_name": settings.EUREKA_APP_NAME, # auth-service 
        "should_register": True, # yes i want to register  so that other services can find me 
        "should_discover": False, # this is so that i can discover other services that are registered  
        "instance_host": settings.EUREKA_INSTANCE_HOST,
        "instance_port": settings.EUREKA_INSTANCE_PORT,
        "home_page_url": settings.EUREKA_HOME_PAGE_URL,
        "status_page_url": settings.EUREKA_STATUS_PAGE_URL,
        "health_check_url": settings.EUREKA_HEALTH_CHECK_URL,
    }


def _shutdown_handler(signum, frame):
    shutdown_eureka_service()
    raise SystemExit(0)


def _install_shutdown_hooks():
    global _shutdown_hooks_installed

    if _shutdown_hooks_installed:
        return

    atexit.register(shutdown_eureka_service)

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, _shutdown_handler)
        except ValueError:
            logger.debug("Skipping signal hook installation outside the main thread.")

    _shutdown_hooks_installed = True


def register_eureka_service():
    # here the magic begins 
    global _registration_started

    if not settings.EUREKA_SERVER_URL:
        return None

    with _registration_lock:
        if _registration_started:
            return eureka_client.get_client()

        client = eureka_client.init(**_build_registration_kwargs())
        _registration_started = True
        _install_shutdown_hooks()
        logger.info(
            "Registered %s with Eureka at %s",
            settings.EUREKA_APP_NAME,
            settings.EUREKA_SERVER_URL,
        )
        return client


def shutdown_eureka_service():
    global _registration_started

    with _registration_lock:
        if not _registration_started and eureka_client.get_client() is None:
            return

        try:
            eureka_client.stop()
            logger.info("Deregistered %s from Eureka", settings.EUREKA_APP_NAME)
        except Exception:
            logger.exception("Failed to deregister %s from Eureka", settings.EUREKA_APP_NAME)
        finally:
            _registration_started = False
