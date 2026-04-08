import asyncio
import uuid
from datetime import datetime

async def research_agent(bus: asyncio.Queue):
    """Listens to market ticks and generates signals based on a 2-tick drop."""
    print("🧠 Research Agent: Online and listening...")
    
    price_history = {}

    while True:
        message = await bus.get()
        
        if message.get("topic") == "market.tick":
            asset = message["asset"]
            current_price = message["current_price"]
            
            if asset not in price_history:
                price_history[asset] = [current_price]
                continue
            
            price_history[asset].append(current_price)
            if len(price_history[asset]) > 3:
                price_history[asset].pop(0)
            
            history = price_history[asset]
            # The "Dumb" Rule: Drop twice consecutively
            if len(history) == 3 and history[0] > history[1] > history[2]:
                
                signal = {
                    "topic": "trade.signal",
                    "trade_id": f"tx_{uuid.uuid4().hex[:6]}",
                    "agent": "research_dumb_reversion",
                    "asset": asset,
                    "intent": "BUY",
                    "confidence": 0.60,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                
                print(f"\n🚨 [Research] SIGNAL GENERATED: Buy {asset} (Price dropped to ₹{current_price})")
                await bus.put(signal)
                
                price_history[asset] = []