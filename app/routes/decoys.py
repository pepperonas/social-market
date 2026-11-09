"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Decoy routes (honeypot, improvement plan 2026-11, B3)

Paths every vulnerability scanner probes and no visitor of this app has a
reason to request. A hit is reported as a security event and then answered
exactly like any other unknown path -- the scanner must not learn that it was
noticed. Nothing is blocked here: the finding is offered to an admin on the
security page (see security_service.block_suggestions).
"""

from flask import Blueprint, abort, request

from app import csrf
from app.services.security_service import DECOY_PATHS, record_decoy_hit

decoys_bp = Blueprint('decoys', __name__)


def _decoy():
    record_decoy_hit(request.path, request.remote_addr)
    abort(404)


# CSRF-exempt: credential stuffers POST to wp-login.php without a token, and a
# CSRF 400 would both hide the hit and answer differently from an unknown path.
_decoy = csrf.exempt(_decoy)

for _path in DECOY_PATHS:
    decoys_bp.add_url_rule(_path, endpoint=f'decoy{DECOY_PATHS.index(_path)}', view_func=_decoy,
                           methods=['GET', 'POST', 'HEAD'], strict_slashes=False)
