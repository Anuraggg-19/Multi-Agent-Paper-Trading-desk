"""
agents/execution_agent.py - Enhanced Execution Agent.

Listens for trade.approved signals (from Risk Agent), executes them
against the PaperPortfolio, and publishes trade.execution receipts
with full fill details, slippage simulation, and portfolio state.
"""

import asyncio
import random
from datetime import datetime


class ExecutionAgent:
    """Executes approved trades on the paper portfolio."""

    def __init__(self, portfolio):
        """
        Args:
            portfolio: core.portfolio.PaperPortfolio instance
        """
        self.portfolio = portfolio
        self.current_prices: dict = {}
        self.stats = {"filled": 0, "rejected": 0}

    # ── Main Loop ────────────────────────────────────────────────────────

    async def run(self, approved_bus: asyncio.Queue):
        """Listen for trade.approved and execute against the portfolio."""
        print("  Execution Agent: Online and waiting for orders...")

        while True:
            message = await approved_bus.get()

            # Track latest prices
            if message.get("topic") == "market.tick":
                self.current_prices[message["asset"]] = message["current_price"]
                continue

            # End of replay
            if message.get("topic") == "market.replay_done":
                continue

            # Only execute approved trades
            if message.get("topic") != "trade.approved":
                continue

            # ── Simulate execution latency + slippage ────────────────
            await asyncio.sleep(random.uniform(0.05, 0.2))

            asset = message["asset"]
            intent = message["intent"]
            qty = message.get("suggested_qty", 1)
            raw_price = message.get("current_price", 0)

            # Slippage: 0.01% to 0.10% adverse movement
            slippage_pct = random.uniform(0.0001, 0.001)
            if intent == "BUY":
                fill_price = round(raw_price * (1 + slippage_pct), 2)
            else:
                fill_price = round(raw_price * (1 - slippage_pct), 2)

            # ── Execute on portfolio ─────────────────────────────────
            if intent == "BUY":
                receipt = self.portfolio.execute_buy(asset, qty, fill_price)
            elif intent == "SELL":
                receipt = self.portfolio.execute_sell(asset, qty, fill_price)
            else:
                continue

            if receipt["status"] == "FILLED":
                self.stats["filled"] += 1
                pnl_str = ""
                if "realized_pnl" in receipt:
                    pnl_str = f" | P&L: Rs.{receipt['realized_pnl']:.2f}"

                print(
                    f"  [Execution] FILLED: {intent} {qty}x {asset} "
                    f"@ Rs.{fill_price:.2f}{pnl_str} | "
                    f"Cash: Rs.{receipt['cash_remaining']:.2f}"
                )
            else:
                self.stats["rejected"] += 1
                print(
                    f"  [Execution] FAILED: {intent} {asset} — "
                    f"{receipt.get('reason', 'Unknown')}"
                )

    # ── Portfolio Snapshot ────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """Get current portfolio state for logging/display."""
        return self.portfolio.to_dict(self.current_prices)

    def print_portfolio(self):
        """Pretty-print the current portfolio."""
        summary = self.get_portfolio_summary()
        print("\n" + "=" * 60)
        print("  PORTFOLIO SNAPSHOT")
        print("=" * 60)
        print(f"  Cash:            Rs.{summary['cash']:>12,.2f}")
        print(f"  Portfolio Value: Rs.{summary['portfolio_value']:>12,.2f}")
        print(f"  Unrealised P&L:  Rs.{summary['unrealized_pnl']:>12,.2f}")
        print(f"  Total P&L:       Rs.{summary['total_pnl']:>12,.2f}")
        print(f"  Open Positions:  {summary['num_positions']}")
        print(f"  Total Trades:    {summary['trade_count']}")

        if self.portfolio.positions:
            print("\n  POSITIONS:")
            for asset, pos in self.portfolio.positions.items():
                current = self.current_prices.get(asset, pos["avg_price"])
                pnl = (current - pos["avg_price"]) * pos["qty"]
                pnl_pct = ((current / pos["avg_price"]) - 1) * 100 if pos["avg_price"] else 0
                print(
                    f"    {asset:25s} | qty={pos['qty']:>4d} | "
                    f"avg=Rs.{pos['avg_price']:>10,.2f} | "
                    f"P&L=Rs.{pnl:>10,.2f} ({pnl_pct:+.1f}%)"
                )
        print("=" * 60 + "\n")
