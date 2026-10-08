import logging
import sys
import threading
from getpass import getpass

from garminconnect import Garmin
from garminconnect.exceptions import GarminConnectAuthenticationError

from app.errors import CoachError as CoachError


class GarminClient:
    """Single athlete adapter; credentials never enter API responses or logs."""

    def __init__(self, token_dir):
        self.token_dir = token_dir
        self.client = None
        self.lock = threading.RLock()
        for name in ("garminconnect", "curl_cffi", "urllib3", "requests"):
            logging.getLogger(name).setLevel(logging.CRITICAL)

    def login(self, interactive=False):
        with self.lock:
            if self.client:
                return self
            try:
                client = Garmin()
                client.login(str(self.token_dir))
            except (GarminConnectAuthenticationError, FileNotFoundError):
                if not interactive or not sys.stdin.isatty():
                    raise CoachError(
                        "Sessione Garmin assente/scaduta. Esegui python -m app.cli login nel terminale.",
                        "login_required",
                        503,
                    ) from None
                email = input("Garmin email: ").strip()
                password = getpass("Garmin password: ")
                client = Garmin(email, password, prompt_mfa=lambda: getpass("Garmin MFA: ").strip())
                try:
                    # Fresh login avoids reusing an API-rejected token cache.
                    client.login()
                    client.client.dump(str(self.token_dir))
                except Exception:
                    raise CoachError(
                        "Login Garmin non riuscito. Verifica credenziali/MFA o riprova più tardi.",
                        "login_failed",
                        503,
                    ) from None
                finally:
                    password = None
                    client.password = None
            except Exception:
                raise CoachError(
                    "Garmin non raggiungibile: riprova più tardi.", "garmin_unavailable", 503
                ) from None
            self.client = client
            return self

    def __getattr__(self, method):
        if method.startswith("_") or method in {"delete_workout", "delete_activity"}:
            raise AttributeError(method)

        def call(*args, **kwargs):
            with self.lock:
                self.login()
                try:
                    return getattr(self.client, method)(*args, **kwargs)
                except GarminConnectAuthenticationError:
                    self.client = None
                    raise CoachError(
                        "Sessione Garmin scaduta. Esegui il login dalla CLI.", "login_required", 503
                    ) from None
                except Exception:
                    raise CoachError(
                        f"Operazione Garmin {method} non riuscita. Nessun dettaglio sensibile viene registrato.",
                        "garmin_request_failed",
                        502,
                    ) from None

        return call
