"""
Tests for cuiows.

These currently fail due to `pytest-curio` being broken.
"""
import pytest
from wsproto.connection import ConnectionState

import cuiows

import logging; logging.basicConfig(level=logging.DEBUG)


@pytest.mark.curio
async def test_ws():
    client = await cuiows.WSClient.connect("ws://echo.websocket.org")
    assert not client.closed
    assert client.state is ConnectionState.OPEN
    await client.close_now()
    assert client.closed


@pytest.mark.curio
async def test_wss():
    client = await cuiows.WSClient.connect("wss://echo.websocket.org")
    assert not client.closed
    assert client.state is ConnectionState.OPEN
    await client.close_now()
    assert client.closed


@pytest.mark.curio
async def test_send_recv():
    client = await cuiows.WSClient.connect("wss://echo.websocket.org")
    assert not client.closed
    assert client.state is ConnectionState.OPEN

    await client.send("Hello, world!")
    event = await client.poll()
    assert event == "Hello, world!"

    await client.send(b"Hello, world!")
    event = await client.poll()
    assert event == b"Hello, world!"

    await client.send(b"Hello, world!")
    event = await client.poll(decode=True)
    assert event == "Hello, world!"

    # cleanup after ourselves
    await client.close_now()
