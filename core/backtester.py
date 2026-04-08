"""
core/backtester.py - Backtesting engine.

Replays historical Fyers data through the full agent pipeline
(Research -> Risk -> Execution) and computes performance metrics.
"""

import asyncio
import math
from datetime import datetime

from core.config import Config
from core.portfolio import PaperPortfolio
from data.fyers_data_fetcher import FyersDataFetcher
from agents.research_agent import ResearchAgent
from agents.risk_agent import RiskAgent
from agents.execution_agent import ExecutionAgent


class BacktestResult:
    """Container for backtest performance metrics."""

    def __init__(self, portfolio: PaperPortfolio, prices: dict, trade_log: list):
        self.portfolio = portfolio
        self.prices = prices
        self.trade_log = trade_log

    @property
    def total_return(self) -> float:
        pv = self.portfolio.get_portfolio_value(self.prices)
        return ((pv / self.portfolio.initial_capital) - 1) * 100

    @property
    def total_trades(self) -> int:
        return len(self.trade_log)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trade_log
                   if t.get("realized_pnl", 0) > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trade_log
                   if t.get("realized_pnl", 0) < 0)

    @property
    def win_rate(self) -> float:
        sells = [t for t in self.trade_log if t.get("side") == "SELL"]
        if not sells:
            return 0.0
        winners = sum(1 for t in sells if t.get("realized_pnl", 0) > 0)
        return (winners / len(sells)) * 100

    @property
    def total_pnl(self) -> float:
        return self.portfolio.get_total_pnl(self.prices)

    @property
    def gross_profit(self) -> float:
        return sum(t.get("realized_pnl", 0) for t in self.trade_log
                   if t.get("realized_pnl", 0) > 0)

    @property
    def gross_loss(self) -> float:
        return abs(sum(t.get("realized_pnl", 0) for t in self.trade_log
                       if t.get("realized_pnl", 0) < 0))

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0
        return self.gross_profit / self.gross_loss

    def print_report(self):
        """Pretty-print the backtest results."""
        print("\n" + "=" * 60)
        print("  BACKTEST PERFORMANCE REPORT")
        print("=" * 60)
        pv = self.portfolio.get_portfolio_value(self.prices)
        print(f"  Initial Capital:  Rs.{self.portfolio.initial_capital:>12,.2f}")
        print(f"  Final Value:      Rs.{pv:>12,.2f}")
        print(f"  Total Return:         {self.total_return:>10.2f}%")
        print(f"  Total P&L:        Rs.{self.total_pnl:>12,.2f}")
        print("-" * 60)
        print(f"  Total Trades:         {self.total_trades:>10d}")
        print(f"  Winning Trades:       {self.winning_trades:>10d}")
        print(f"  Losing Trades:        {self.losing_trades:>10d}")
        print(f"  Win Rate:             {self.win_rate:>10.1f}%")
        print(f"  Profit Factor:        {self.profit_factor:>10.2f}")
        print(f"  Gross Profit:     Rs.{self.gross_profit:>12,.2f}")
        print(f"  Gross Loss:       Rs.{self.gross_loss:>12,.2f}")
        print("-" * 60)
        print(f"  Cash Remaining:   Rs.{self.portfolio.cash:>12,.2f}")
        print(f"  Open Positions:       {self.portfolio.get_open_position_count():>10d}")

        if self.portfolio.positions:
            print("\n  OPEN POSITIONS AT END:")
            for asset, pos in self.portfolio.positions.items():
                cur = self.prices.get(asset, pos["avg_price"])
                upnl = (cur - pos["avg_price"]) * pos["qty"]
                print(f"    {asset:25s} qty={pos['qty']:>4d} "
                      f"avg=Rs.{pos['avg_price']:.2f} "
                      f"unrealised=Rs.{upnl:.2f}")

        print("=" * 60 + "\n")


class Backtester:
    """Orchestrates a full historical backtest."""

    def __init__(
        self,
        symbols: list = None,
        start_date: str = None,
        end_date: str = None,
        initial_capital: float = None,
        resolution: str = None,
    ):
        self.symbols = symbols or Config.TRADING_SYMBOLS
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital or Config.PAPER_PORTFOLIO_CAPITAL
        self.resolution = resolution or Config.HISTORY_RESOLUTION

    async def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        print("\n" + "=" * 60)
        print("  BACKTESTER STARTING")
        print(f"  Symbols:    {', '.join(self.symbols)}")
        print(f"  Period:     {self.start_date} to {self.end_date}")
        print(f"  Resolution: {self.resolution}min candles")
        print(f"  Capital:    Rs.{self.initial_capital:,.2f}")
        print("=" * 60 + "\n")

        # ── Initialise components ────────────────────────────────────
        portfolio = PaperPortfolio(self.initial_capital)

        fetcher = FyersDataFetcher(
            client_id=Config.FYERS_CLIENT_ID,
            access_token=Config.FYERS_ACCESS_TOKEN,
            symbols=self.symbols,
        )

        research = ResearchAgent()
        risk = RiskAgent(portfolio, Config)
        execution = ExecutionAgent(portfolio)

        # ── Create the two buses ─────────────────────────────────────
        data_bus = asyncio.Queue()       # data -> research
        signal_bus = asyncio.Queue()     # research -> risk
        approved_bus = asyncio.Queue()   # risk -> execution

        # ── Replay historical data for each symbol ───────────────────
        replay_tasks = []
        for symbol in self.symbols:
            replay_tasks.append(
                fetcher.replay_historical(
                    bus=data_bus,
                    symbol=symbol,
                    resolution=self.resolution,
                    from_date=self.start_date,
                    to_date=self.end_date,
                    speed=0,  # instant replay
                )
            )

        # Wait for all data to be loaded into the bus
        replay_results = await asyncio.gather(*replay_tasks)

        total_candles = sum(len(r) if r is not None and not r.empty else 0 for r in replay_results)
        print(f"\n  Loaded {total_candles} total candles into data bus")

        # ── Process all messages through the pipeline ────────────────
        # We process synchronously: drain data_bus through research,
        # then signal_bus through risk, then approved_bus through execution

        # Step 1: Research processes all ticks
        processed = 0
        while not data_bus.empty():
            msg = await data_bus.get()
            if msg.get("topic") == "market.tick":
                # Manually invoke research logic
                await research.run_single(signal_bus, msg)
                processed += 1
            elif msg.get("topic") == "market.replay_done":
                await signal_bus.put(msg)

        print(f"  Research processed {processed} ticks, generated signals")

        # Step 2: Risk evaluates all signals
        approved_count = 0
        rejected_count = 0
        while not signal_bus.empty():
            msg = await signal_bus.get()
            if msg.get("topic") == "market.tick":
                risk.current_prices[msg["asset"]] = msg["current_price"]
                execution.current_prices[msg["asset"]] = msg["current_price"]
            elif msg.get("topic") == "trade.signal":
                passed, reasons = risk._evaluate(msg)
                if passed:
                    msg["topic"] = "trade.approved"
                    await approved_bus.put(msg)
                    approved_count += 1
                else:
                    rejected_count += 1
            # ignore other topics

        print(f"  Risk approved {approved_count}, rejected {rejected_count}")

        # Step 3: Execution fills approved trades
        while not approved_bus.empty():
            msg = await approved_bus.get()
            if msg.get("topic") == "trade.approved":
                intent = msg["intent"]
                asset = msg["asset"]
                qty = msg.get("suggested_qty", 1)
                price = msg.get("current_price", 0)

                if intent == "BUY":
                    receipt = portfolio.execute_buy(asset, qty, price)
                elif intent == "SELL":
                    receipt = portfolio.execute_sell(asset, qty, price)

        # Build final prices map for valuation
        final_prices = dict(execution.current_prices)

        result = BacktestResult(portfolio, final_prices, portfolio.trade_history)
        result.print_report()
        return result
