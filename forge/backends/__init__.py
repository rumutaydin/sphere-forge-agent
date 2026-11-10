from .base import CadBackend, ExecResult, describe
from .cadquery_backend import CadQueryBackend

BACKENDS = {"cadquery": CadQueryBackend}


def get_backend(name: str = "cadquery") -> CadBackend:
    return BACKENDS[name]()
