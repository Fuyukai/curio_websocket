import logging
import typing

import curio
from curio.task import Task
from curio.io import Socket
from curio.ssl import create_default_context, CurioSSLContext
import yarl

from wsproto.connection import WSConnection, CLIENT, ConnectionEstablished, \
    ConnectionClosed
from wsproto.events import DataReceived, BytesReceived, TextReceived

from cuiows.exc import WebsocketClosedError

# Sentinel value.
CONNECTION_FAILED = object()


class WSClient(object):
    """
    A basic websocket client.
    """
    def __init__(self, host: str, port: int = 443, path: str = "/", use_ssl: bool = True, *,
                 ssl_context: CurioSSLContext = None):
        self.host = host
        self.port = port

        if use_ssl:
            if ssl_context is not None:
                self.ssl_context = ssl_context
            else:
                self.ssl_context = create_default_context()

        else:
            self.ssl_context = None

        #: The wsproto state machine used for this connection.
        self.ws_state_machine = WSConnection(CLIENT, host=self.host, resource=path)

        #: The current curio socket associated with this client.
        self.connection = None  # type: Socket

        #: The current logger for this client.
        self.logger = logging.getLogger("cuiows")

        #: The current queue of events to be handled by client code.
        self.event_queue = curio.Queue()

        #: The closed flag. This signifies if the websocket has closed or not.
        self._closed = curio.Event()

        #: The connection closed event. This is used to retrieve how the connection was closed.
        self._closed_event = None  # type: ConnectionClosed

        #: The current reader task.
        self._rd_task = None  # type: Task

        #: The ready event. This is set when a ready event is received.
        self._ready = curio.Event()

        #: The current data buffer.
        #: This is used to buffer incoming data when the message is not complete.
        self._buffer = b""
        self._text_buffer = ""

    @property
    def closed(self):
        """
        :return: If this connection is closed or not.
        """
        return self._closed.is_set()

    @property
    def ready(self):
        """
        :return: If this connection is ready or not.
        """
        return self._ready.is_set()

    @property
    def state(self):
        return self.ws_state_machine._state

    @classmethod
    async def connect(cls, url: str, *args, **kwargs) -> 'WSClient':
        """
        Opens a connection to a websocket server.

        :param url: The websocket url, e.g ``wss://echo.websocket.org``.
        :return: A new :class:`WSClient` object that is connected to the server.
        """
        url = yarl.URL(url)

        # If the scheme is `wss`, then only then do we use SSL.
        # Otherwise, all connections are over websocket.
        if url.scheme == "wss":
            ssl = kwargs.pop("ssl_context", create_default_context())
        else:
            ssl = None

        path = url.path + "?" + url.raw_query_string

        return await cls.connect_host_port(url.host, url.port, path,
                                           use_ssl=ssl is not None, ssl_context=ssl)

    @classmethod
    async def connect_host_port(cls, host: str, port: int = 443, path: str = "/",
                                *args, **kwargs) -> 'WSClient':
        """
        Opens a connection to a websocket server.

        :param host: The server address to connect to.
        :param port: The port of the server to connect to.
        :param path: The path to request when connecting to the server.
        :return: A new :class:`WSClient` object that is connected to the server.
        """
        obb = cls(host, port, path, *args, **kwargs)
        obb.logger.debug("Opening websocket connection to {}:{}{}".format(host, port, path))
        if obb.ssl_context:
            server_hostname = host
        else:
            server_hostname = None

        connection = await curio.open_connection(host=obb.host, port=obb.port, ssl=obb.ssl_context,
                                                 server_hostname=server_hostname)  # type: Socket
        obb.logger.debug("Connection {} opened, sending message to open the websocket".format(connection))
        obb.connection = connection

        # Write the opening event.
        opening_bytes = obb.ws_state_machine.bytes_to_send()
        await obb.connection.send(opening_bytes)
        obb.logger.debug("Established websocket connection!")

        obb._rd_task = await curio.spawn(obb._reader_task())

        # Wait for the ready event.
        if kwargs.pop("wait_for_ready", True):
            await obb.wait_for_ready()

        return obb

    async def _fail(self, event: ConnectionClosed):
        """
        Fails the websocket connection.

        This will set the closed flag, and close the connection.
        """
        await self._closed.set()
        self._closed_event = event

        # This is hacky, but it cancels all the tasks currently waiting on the queue.
        try:
            queue = self.event_queue._get_waiting._queue.copy()
        except AttributeError:
            # Old versions of curio
            queue = self.event_queue._get_waiting.copy()

        for task in queue:
            # Put a CONNECTION_FAILED onto the queue, so that they all wake up and raise.
            await self.event_queue.put(CONNECTION_FAILED)

    async def _reader_task(self):
        """
        A reader tasked spawned by curio to read data.

        This will poll the connection, feed bytes to the state machine, then add the events to the queue.
        """
        if self.closed:
            return

        async with self.connection:
            while True:
                try:
                    data = await self.connection.recv(65535)
                except (OSError, ConnectionError):
                    await self._closed.set()
                    return

                self.ws_state_machine.receive_bytes(data)
                for event in self.ws_state_machine.events():
                    self.logger.debug("Received event {}".format(event))
                    # Special-case some events.
                    if isinstance(event, ConnectionClosed):
                        await self._fail(event)
                        return

                    if isinstance(event, ConnectionEstablished):
                        await self._ready.set()
                        continue

                    if isinstance(event, BytesReceived):
                        # Make sure we've got the end of the event first.
                        if event.message_finished:
                            event.data = self._buffer + event.data
                            self._buffer = b""
                            await self.event_queue.put(event)
                        else:
                            # Buffer the event data, for later usage.
                            self._buffer += event.data

                    elif isinstance(event, TextReceived):
                        # I honestly don't care enough to make this better
                        # It works(tm)
                        if event.message_finished:
                            event.data = self._text_buffer + event.data
                            self._text_buffer = ""
                            await self.event_queue.put(event)
                        else:
                            # Buffer the event data, for later usage.
                            self._text_buffer += event.data

    # User API
    async def wait_for_ready(self):
        """
        Waits until the websocket is open.
        """
        await self._ready.wait()
        return True

    async def wait_for_close(self):
        """
        Waits until the websocket is closed.

        :return: The close event.
        """
        await self._closed.wait()
        return self._closed_event

    async def close(self, code: int=1000, reason=None, wait: bool=True):
        """
        Closes the websocket.

        This will not immediately close the connection - it will send a CLOSE frame. You can poll the close event
        with :meth:`poll` afterwards.

        :param code: The close code to send.
        :param reason: The close reason to send.
        :param wait: If the client should wait until the server is ready to close the connection.
        """
        self.ws_state_machine.close(code=code, reason=reason)
        data = self.ws_state_machine.bytes_to_send()
        try:
            await self.connection.send(data)
        except (OSError, ConnectionError):
            pass

        if wait:
            await self.wait_for_close()

        if self._closed_event is None:
            self._closed_event = ConnectionClosed(code=code, reason=reason)

        self.logger.debug("Cancelling reader task")
        await self._rd_task.cancel()
        await self.connection.close()

    async def close_now(self, code: int=1000, reason=None):
        """
        Forcefully closes the client websocket.

        This will send a close frame, then close the connection.
        """
        await self.close(code, reason, wait=False)
        await self._fail(self._closed_event)
        self.logger.debug("Closed websocket connection")

    async def poll_event(self) -> DataReceived:
        """
        Polls for the next event.
        :return: The event data received from the websocket.
        """
        if self.closed:
            raise WebsocketClosedError(self._closed_event.code, self._closed_event.reason)

        i = await self.event_queue.get()
        if i == CONNECTION_FAILED:
            raise WebsocketClosedError(self._closed_event.code, self._closed_event.reason)

        return i

    async def poll(self, decode: bool=False, *, encoding: str="utf-8") -> typing.Union[str, bytes]:
        """
        Polls for the next event data.

        This will retrieve the data from the event frame, if possible.

        :param decode: If a BytesReceived object is encounted, should it be automatically decoded?
        :param encoding: The encoding to automatically decode as.
        :return: The data from the connection.
        """
        event = await self.poll_event()
        if isinstance(event, TextReceived):
            return event.data

        elif isinstance(event, BytesReceived):
            if decode:
                return event.data.decode(encoding)
            else:
                return bytes(event.data)

    async def send(self, data: typing.Union[str, bytes], *, encoding: str="utf-8"):
        """
        Send a frame to the websocket.

        :param data: The data to send.
            This can be str or bytes. This will change the type of data frame sent.
        :param encoding: If str data is sent, this is the encoding the data will be sent as.
        """
        if self.closed:
            raise WebsocketClosedError(self._closed_event.code, self._closed_event.reason)

        if not self.ready:
            await self.wait_for_ready()

        self.ws_state_machine.send_data(data)
        bytes = self.ws_state_machine.bytes_to_send()

        await self.connection.send(bytes)

