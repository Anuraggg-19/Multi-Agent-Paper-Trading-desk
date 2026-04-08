import asyncio
from datetime import datetime

async def execution_agent(bus: asyncio.Queue):
    """Listens for approved signals and simulates the trade execution."""
    print("⚡ Execution Agent: Online and waiting for orders...")
    
    while True:
        message = await bus.get()
        
        if message.get("topic") == "trade.signal":
            
            # Simulate latency and minor slippage
            await asyncio.sleep(0.5) 
            simulated_fill_price = message.get("current_price", 0) * 1.001 
            
            execution_receipt = {
                "topic": "trade.execution",
                "trade_id": message["trade_id"],
                "agent": "executor_market_order",
                "status": "FILLED",
                "asset": message["asset"],
                "intent": message["intent"],
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            
            print(f"✅ [Execution] ORDER FILLED: {message['intent']} {message['asset']} | TX: {message['trade_id']}\n")
            
            await bus.put(execution_receipt)