"""Request-local rollout eligibility, propagated through async/sync boundaries."""
from contextvars import ContextVar

face_client_supported = ContextVar('face_client_supported', default=False)
