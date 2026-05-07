import asyncio
from asyncua import Client
import os
from dotenv import load_dotenv
load_dotenv()

OPC_URL = "opc.tcp://10.33.126.101:51800"

async def kill_sessions():
    client = Client(OPC_URL)
    client.set_user(os.getenv("OPC_USER"))
    client.set_password(os.getenv("OPC_PASSWORD"))
    try:
        await client.connect()
        print("Connected")
        # Cancel all subscriptions and close session cleanly
        await client.disconnect()
        print("Disconnected cleanly — session freed")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(kill_sessions())