import asyncio
import json
import websockets

async def test():
    uri = 'ws://127.0.0.1:5000'

    # Client 1 connects
    c1 = await websockets.connect(uri)
    await c1.send(json.dumps({'type': 'connect', 'username': 'Alice'}))
    r1 = json.loads(await c1.recv())
    print(f'[1] Alice connected: {r1}')

    # Alice should get participants list
    p1 = json.loads(await c1.recv())
    print(f'[1] Alice participants: {p1}')

    # Wait a bit
    await asyncio.sleep(1)

    # Client 2 connects
    c2 = await websockets.connect(uri)
    await c2.send(json.dumps({'type': 'connect', 'username': 'Bob'}))
    r2 = json.loads(await c2.recv())
    print(f'[2] Bob connected: {r2}')

    # Bob should get participants list
    p2 = json.loads(await c2.recv())
    print(f'[2] Bob participants: {p2}')

    # Alice should get join notification + updated participants
    msgs = []
    for _ in range(3):
        try:
            m = await asyncio.wait_for(c1.recv(), timeout=1)
            msgs.append(json.loads(m))
        except asyncio.TimeoutError:
            break
    for m in msgs:
        print(f'[1] Alice received: {m}')

    # Wait for processing
    await asyncio.sleep(2)

    print('\nTest done. Check client.log for details.')

asyncio.run(test())
