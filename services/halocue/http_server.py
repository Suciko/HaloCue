"""Local HTTP runtime sized for the editor's parallel startup assets."""

from http.server import ThreadingHTTPServer


class LocalHTTPServer(ThreadingHTTPServer):
    # Python 3.10–3.13 default to five pending connections. The browser and
    # gateway can open a larger burst before a busy startup thread accepts it.
    request_queue_size = 64
