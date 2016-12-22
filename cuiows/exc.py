class WebsocketError(Exception):
    """
    The base class for all websocket exceptions.
    """


class WebsocketClosedError(WebsocketError):
    """
    Raised when a connection is closed.

    :ivar code: The close code.
    :ivar reason: The reason for the close.
    """
    def __init__(self, code: int, reason: str):
        self.code = code
        self.reason = reason
