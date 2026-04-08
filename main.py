import asyncio

# Import the isolated components
from data.yfinance_streamer import yfinance_data_streamer
from agents.research_agent import research_agent
from agents.execution_agent import execution_agent

async def main():
    print("🚀 Initializing Algo Trading Simulation...")
    
    # 1. Create the central message bus
    message_bus = asyncio.Queue()
    stocks = ["RELIANCE.NS", "HDFCBANK.NS"]
    
    # 2. Spin up the microservices as background tasks
    # We pass the same message_bus to all of them so they can communicate
    asyncio.create_task(yfinance_data_streamer(message_bus, stocks))
    asyncio.create_task(research_agent(message_bus))
    asyncio.create_task(execution_agent(message_bus))
    
    # 3. Keep the main thread alive forever
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 System shut down manually.")