"""
Base class for node operations.
"""
from kitchen.ssh import SSHSession


class BaseNode:
    """
    A base class for operations on a remote node (master or worker).
    """

    def __init__(self, session: SSHSession, verbose: bool = False):
        self.session = session
        self.verbose = verbose
