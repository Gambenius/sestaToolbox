import asyncio
from asyncua import Client
import os
from dotenv import load_dotenv
load_dotenv()

OPC_URL = "opc.tcp://10.33.126.101:51800"
 
# Add as many points as you need — just use POINTNAME.Value pattern
POINTS = {
    "F002MIS2":     "ns=3;s=F002MIS2.Value",
    "X44FT_GAS": "ns=3;s=X44FT_GAS.Value",
}
 
async def main():
    client = Client(OPC_URL, timeout=10)
    client.set_user(os.getenv("OPC_USER"))
    client.set_password(os.getenv("OPC_PASSWORD"))
    client.session_timeout = 60_000  # milliseconds
    try:
        await client.connect()
        print("Connected\n")
    
        nodes = {name: client.get_node(node_id) for name, node_id in POINTS.items()}
    
        while True:
            for name, node in nodes.items():
                try:
                    value = await node.read_value()
                    print(f"{name}: {value}")
                except Exception as e:
                    print(f"{name}: ERROR — {e}")
            print("---")
            await asyncio.sleep(1)
    finally:
        await client.disconnect()  # always runs even on Ctrl+C
        print("Disconnected")
    
asyncio.run(main())