#!/usr/bin/env python3
import asyncio

import aiohttp


async def test_connection():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:9222/json") as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Found {len(data)} tabs:")
                    for tab in data:
                        print(f"  - {tab.get('url', 'Unknown')}")
                        print(f"    WebSocket: {tab.get('webSocketDebuggerUrl', 'None')}")
                else:
                    print(f"Response: {await resp.text()}")
    except Exception as e:
        print(f"Connection error: {e}")


if __name__ == "__main__":
    asyncio.run(test_connection())
