import hashlib
import secrets
import uuid
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.errors import CoachError
from app.platform.tables import Athlete, AuthSession, RateLimit

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(24))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(password_hash, password):
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


class AccountService:
    def __init__(self, store):
        self.store = store
        self.settings = store.settings

    def throttle(self, key, maximum, seconds=900):
        # Store only digests; do not log account identifiers or client IPs.
        key = token_hash(key)
        now = self.settings.now().timestamp()
        for _ in range(3):
            try:
                with self.store.transaction() as session:
                    session.execute(delete(RateLimit).where(RateLimit.window_end <= now))
                    result = session.execute(
                        update(RateLimit)
                        .where(RateLimit.key == key, RateLimit.attempts < maximum)
                        .values(attempts=RateLimit.attempts + 1)
                    )
                    if result.rowcount:
                        return
                    if session.get(RateLimit, key):
                        raise CoachError("Too many attempts. Try again later.", "rate_limited", 429)
                    session.add(RateLimit(key=key, attempts=1, window_end=now + seconds))
                return
            except IntegrityError:
                continue
        raise CoachError("Too many attempts. Try again later.", "rate_limited", 429)

    def register(self, email, password, timezone, client_ip):
        if not self.settings.registration_enabled:
            raise CoachError("Registration is closed", "registration_closed", 403)
        self.throttle(f"register:{client_ip}", 5, seconds=3600)
        hashed = hasher.hash(password)
        now = self.settings.now().isoformat()
        athlete = Athlete(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=hashed,
            timezone=timezone,
            created_at=now,
        )
        try:
            with self.store.transaction() as session:
                session.add(athlete)
            return {"id": athlete.id, "email": athlete.email, "timezone": athlete.timezone}
        except IntegrityError:
            raise CoachError(
                "Account cannot be created with these details", "registration_failed", 409
            ) from None

    def login(self, email, password, client_ip):
        self.throttle(f"login-ip:{client_ip}", 40)
        self.throttle(f"login-account:{email}", 12)
        with self.store.sessions() as session:
            athlete = session.scalar(select(Athlete).where(Athlete.email == email))
            password_hash = athlete.password_hash if athlete else dummy_hash
            athlete_id = athlete.id if athlete else None
        if not verify_password(password_hash, password) or athlete_id is None:
            raise CoachError("Invalid email or password", "unauthorized", 401)
        token = secrets.token_urlsafe(32)
        now = self.settings.now()
        expires = now + timedelta(hours=self.settings.session_hours)
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, athlete_id)
            # A concurrent password change/deletion must not issue a new session.
            if athlete.password_hash != password_hash:
                raise CoachError("Invalid email or password", "unauthorized", 401)
            session.execute(delete(AuthSession).where(AuthSession.expires_at <= now.timestamp()))
            if hasher.check_needs_rehash(password_hash):
                athlete.password_hash = hasher.hash(password)
            session.add(
                AuthSession(
                    token_hash=token_hash(token),
                    athlete_id=athlete_id,
                    expires_at=expires.timestamp(),
                    created_at=now.isoformat(),
                )
            )
        return {"access_token": token, "token_type": "bearer", "expires_at": expires.isoformat()}

    def authenticate(self, token):
        if not token or len(token) > 200:
            raise CoachError("Authentication required", "unauthorized", 401)
        with self.store.sessions() as session:
            auth = session.get(AuthSession, token_hash(token))
            if not auth or auth.expires_at <= self.settings.now().timestamp():
                raise CoachError("Authentication required", "unauthorized", 401)
            athlete = session.get(Athlete, auth.athlete_id)
            if not athlete:
                raise CoachError("Authentication required", "unauthorized", 401)
            return {
                "id": athlete.id,
                "email": athlete.email,
                "timezone": athlete.timezone,
                "token_hash": auth.token_hash,
            }

    def logout(self, identity):
        with self.store.transaction() as session:
            session.execute(
                delete(AuthSession).where(
                    AuthSession.token_hash == identity["token_hash"],
                    AuthSession.athlete_id == identity["id"],
                )
            )

    def delete_account(self, identity, password):
        self.throttle(f"delete:{identity['id']}", 5)
        with self.store.sessions() as session:
            athlete = session.get(Athlete, identity["id"])
            old_hash = athlete.password_hash if athlete else dummy_hash
        if not verify_password(old_hash, password):
            raise CoachError("Password verification failed", "unauthorized", 401)
        with self.store.transaction() as session:
            athlete = self.store.lock_athlete(session, identity["id"])
            if athlete.password_hash != old_hash:
                raise CoachError("Password verification failed", "unauthorized", 401)
            session.execute(delete(Athlete).where(Athlete.id == identity["id"]))
