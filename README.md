## cuiows

A websocket library for [curio](https://github.com/dabeaz/curio).

### Installation

`pip install -U cuiows`

### Limitations

 - Currently, this only supports the client.
 
### Example

```py
async def main():
    client = await WSClient.connect("ws://echo.websocket.org")
    await client.send("Hello, world!")
    
    data = await client.poll()
    print(data)  # Hello, world!
```

