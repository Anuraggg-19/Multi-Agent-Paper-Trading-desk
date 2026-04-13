"""
main.py - Multi-Agent Paper Trading Platform Orchestrator.

Usage:
  python main.py --live                     Live paper trading (market hours)
  python main.py --backtest                 Backtest with defaults (last 30 days)
  python main.py --backtest --from 2026-03-01 --to 2026-04-01
"""

import sys
import asyncio
import argparse

from core.config import Config
from core.portfolio import PaperPortfolio
from data.fyers_data_fetcher import FyersDataFetcher
from agents.research_agent import ResearchAgent
from agents.risk_agent import RiskAgent
from agents.execution_agent import ExecutionAgent
from core.backtester import Backtester


# ═════════════════════════════════════════════════════════════════════════
#  LIVE MODE
# ═════════════════════════════════════════════════════════════════════════

async def run_live():
    """Start all agents for live paper trading."""
    from datetime import datetime, timedelta
    import pandas as pd

    print("\n" + "=" * 60)
    print("  MULTI-AGENT PAPER TRADING PLATFORM")
    print("  Mode: LIVE PAPER TRADING")
    print("=" * 60)

    if not Config.validate():
        sys.exit(1)

    # Initialise shared portfolio
    portfolio = PaperPortfolio(Config.PAPER_PORTFOLIO_CAPITAL)
    print(f"\n  Portfolio initialised: Rs.{Config.PAPER_PORTFOLIO_CAPITAL:,.2f}")

    # Initialise data fetcher
    fetcher = FyersDataFetcher(
        client_id=Config.FYERS_CLIENT_ID,
        access_token=Config.FYERS_ACCESS_TOKEN,
        symbols=Config.TRADING_SYMBOLS,
    )

    # Verify API connection
    profile = await asyncio.get_event_loop().run_in_executor(
        None, fetcher.get_profile
    )
    if profile.get("s") == "ok":
        name = profile.get("data", {}).get("name", "Unknown")
        print(f"  Connected to Fyers API as: {name}")
    else:
        print(f"  WARNING: Could not verify API connection: {profile}")

    # Initialise agents
    research = ResearchAgent()
    risk = RiskAgent(portfolio, Config)
    execution = ExecutionAgent(portfolio)

    # Create message buses
    # data_bus:     data_fetcher -> research_agent
    # signal_bus:   research_agent -> risk_agent  (ticks + signals)
    # approved_bus: risk_agent -> execution_agent (ticks + approved trades)
    data_bus = asyncio.Queue()
    signal_bus = asyncio.Queue()
    approved_bus = asyncio.Queue()

    # Spin up all agents as concurrent tasks
    tasks = [
        asyncio.create_task(
            fetcher.live_stream(data_bus, Config.POLL_INTERVAL_SECONDS),
            name="data_fetcher"
        ),
        asyncio.create_task(
            research.run(data_bus, signal_bus),
            name="research_agent"
        ),
        asyncio.create_task(
            risk.run(signal_bus, approved_bus),
            name="risk_agent"
        ),
        asyncio.create_task(
            execution.run(approved_bus),
            name="execution_agent"
        ),
        asyncio.create_task(
            _periodic_portfolio_log(execution),
            name="portfolio_logger"
        ),
    ]

    print(f"\n  All agents online. Tracking: {', '.join(Config.TRADING_SYMBOLS)}")
    print("  Press Ctrl+C to stop.\n")

    # Keep alive
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


async def _periodic_portfolio_log(execution: ExecutionAgent, interval: int = 60):
    """Print portfolio snapshot every N seconds."""
    while True:
        await asyncio.sleep(interval)
        execution.print_portfolio()


# ═════════════════════════════════════════════════════════════════════════
#  BACKTEST MODE
# ═════════════════════════════════════════════════════════════════════════

async def run_backtest(start_date: str, end_date: str):
    """Run historical backtest."""
    if not Config.validate():
        sys.exit(1)

    backtester = Backtester(
        symbols=Config.TRADING_SYMBOLS,
        start_date=start_date,
        end_date=end_date,
        initial_capital=Config.PAPER_PORTFOLIO_CAPITAL,
        resolution=Config.HISTORY_RESOLUTION,
    )
    result = await backtester.run()
    return result


# ═════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Paper Trading Platform"
    )
    parser.add_argument("--live", action="store_true",
                        help="Run in live paper trading mode")
    parser.add_argument("--backtest", action="store_true",
                        help="Run historical backtest")
    parser.add_argument("--from-date", dest="from_date", type=str, default=None,
                        help="Backtest start date (yyyy-mm-dd)")
    parser.add_argument("--to-date", dest="to_date", type=str, default=None,
                        help="Backtest end date (yyyy-mm-dd)")

    args = parser.parse_args()

    if args.backtest:
        from datetime import datetime, timedelta
        start = args.from_date or datetime.now().strftime("%Y-%m-%d")
        end = args.to_date or datetime.now().strftime("%Y-%m-%d")
        try:
            asyncio.run(run_backtest(start, end))
        except KeyboardInterrupt:
            print("\n  Backtest interrupted.")

    elif args.live:
        try:
            asyncio.run(run_live())
        except KeyboardInterrupt:
            print("\n  System shut down manually.")

    else:
        parser.print_help()
        print("\n  Example:")
        print("    python main.py --live")
        print("    python main.py --backtest")
        print("    python main.py --backtest --from-date 2026-03-01 --to-date 2026-04-01")


if __name__ == "__main__":
    main()
