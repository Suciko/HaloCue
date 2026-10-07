"""Local HTTP runtime sized for the editor's parallel startup assets."""

from http.server import ThreadingHTTPServer
import sys


class LocalHTTPServer(ThreadingHTTPServer):
    # Python 3.10–3.13 default to five pending connections. The browser and
    # gateway can open a larger burst before a busy startup thread accepts it.
    request_queue_size = 64

    def handle_error(self, request, client_address):
        # Navigation and aborted fetches routinely close a browser socket.
        # Printing a traceback from daemon workers during shutdown can crash
        # Python's stderr finalizer; preserve diagnostics for all other errors.
        if isinstance(
            sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
        ):
            return
        super().handle_error(request, client_address)
