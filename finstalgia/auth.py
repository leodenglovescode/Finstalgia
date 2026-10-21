import secrets
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field


@dataclass
class Session:
    sid: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    device: str = field(default_factory=lambda: secrets.token_hex(16))
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    token: str | None = None
    user_id: str = ""
    name: str = ""
    mode: str = "modern"
    grants: OrderedDict = field(default_factory=OrderedDict)
    artwork: OrderedDict = field(default_factory=OrderedDict)


class Sessions:
    """Single process only. Tokens and media grants never leave this store."""

    def __init__(self, config):
        self.config = config
        self.values: dict[str, Session] = {}

    def alive(self, session):
        now = time.monotonic()
        maximum = self.config.max_seconds if session.token else 600
        return now - session.created < maximum and now - session.touched < self.config.idle_seconds

    def prune(self):
        for sid, session in list(self.values.items()):
            if not self.alive(session):
                self.drop(sid)

    def new(self, **values):
        self.prune()
        if len(self.values) >= self.config.max_sessions:
            raise ValueError("Too many active sessions; try again later")
        session = Session(**values)
        self.values[session.sid] = session
        return session

    def get(self, sid):
        session = self.values.get(sid)
        if session and not self.alive(session):
            self.drop(sid)
            return None
        if session:
            session.touched = time.monotonic()
        return session

    def drop(self, sid):
        session = self.values.pop(sid, None)
        if session:
            session.token = None
            session.grants.clear()


class LoginLimiter:
    """Bounded per-address and global attempt windows; trust no forwarded IP headers."""

    def __init__(self):
        self.addresses = OrderedDict()
        self.global_attempts = deque()

    def allow(self, address):
        now = time.monotonic()
        while self.global_attempts and now - self.global_attempts[0] >= 60:
            self.global_attempts.popleft()
        attempts = self.addresses.setdefault(address, deque())
        while attempts and now - attempts[0] >= 60:
            attempts.popleft()
        self.addresses.move_to_end(address)
        if len(self.addresses) > 2048:
            self.addresses.popitem(last=False)
        if len(attempts) >= 5 or len(self.global_attempts) >= 100:
            return False
        attempts.append(now)
        self.global_attempts.append(now)
        return True
