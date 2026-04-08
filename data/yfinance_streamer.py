import asyncio
import yfinance as yf
import json 
import random
from datetime import datetime

async def yfinance_data_streamer(bus: asyncio.Queue, symbols: list):
    """Fetches live-ish data from Yahoo and publishes it to the message bus."""
    print(f"📡 Starting market data stream for: {symbols}")
    
    while True:
        for symbol in symbols:
            try:
                # Fetch the latest 1-minute candle
                ticker = yf.Ticker(symbol)
                data = ticker.history(period="1d", interval="1m")
                
                if not data.empty:
                    latest = data.iloc[-1]
                    real_price = latest["Close"]
                    
                    # 🛠️ WEEKEND HACK: Artificially fluctuate the price by +/- 0.5%
                    noise = real_price * random.uniform(-0.005, 0.005)
                    simulated_price = round(real_price + noise, 2)
                    
                    tick_event = {
                        "topic": "market.tick",
                        "asset": symbol.replace(".NS", ""), 
                        "current_price": simulated_price, # Use the noisy price
                        "volume": int(latest["Volume"]),
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                    
                    # To prove data is flowing, let's print the fake ticks
                    print(f"📈 [Market Feed] {tick_event['asset']}: ₹{simulated_price}")
                    
                    await bus.put(tick_event)
                
            except Exception as e:
                print(f"⚠️ Error fetching {symbol}: {e}")
            
            # Anti-Ban Protection 1: Sleep slightly between fetching different stocks
            await asyncio.sleep(2) 
        
        # Anti-Ban Protection 2: Wait 60 seconds before checking the market again
        print("⏳ Polling cycle complete. Waiting 60 seconds...")
        await asyncio.sleep(60)

# --- Test Environment ---
async def main():
    # 1. Create the central message bus
    message_bus = asyncio.Queue()
    stocks = ["RELIANCE.NS", "HDFCBANK.NS"]
    
    # 2. Start the data fetcher as a background task
    fetch_task = asyncio.create_task(yfinance_data_streamer(message_bus, stocks))
    
    # 3. Simulate an Agent listening to the bus
    print("🤖 System listening for market events...")
    while True:
        # The agent waits until a message drops onto the bus
        message = await message_bus.get()
        
        if message["topic"] == "market.tick":
             print(f"📥 [Research Agent Logs] Received tick: {message['asset']} at ₹{message['current_price']}")

if __name__ == "__main__":
    # Run the async event loop
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 System shut down manually.")