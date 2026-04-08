"""
core/portfolio.py - Paper Portfolio Manager.
Tracks positions, cash, trade history, and P&L for simulated trading.
"""

import json
import threading
from datetime import datetime


class PaperPortfolio:
    """Thread-safe paper trading portfolio."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict = {}        # {asset: {"qty": int, "avg_price": float}}
        self.trade_history: list = []    # chronological trade log
        self._lock = threading.Lock()
        self._start_of_day_value = initial_capital

    # ── Core Operations ──────────────────────────────────────────────────

    def execute_buy(self, asset: str, qty: int, price: float) -> dict:
        """Execute a paper BUY order. Returns receipt dict."""
        cost = qty * price
        with self._lock:
            if cost > self.cash:
                return {"status": "REJECTED", "reason": "Insufficient cash",
                        "required": cost, "available": self.cash}

            self.cash -= cost

            if asset in self.positions:
                pos = self.positions[asset]
                total_qty = pos["qty"] + qty
                pos["avg_price"] = ((pos["avg_price"] * pos["qty"]) + cost) / total_qty
                pos["qty"] = total_qty
            else:
                self.positions[asset] = {"qty": qty, "avg_price": price}

            receipt = {
                "status": "FILLED",
                "side": "BUY",
                "asset": asset,
                "qty": qty,
                "fill_price": price,
                "cost": cost,
                "cash_remaining": self.cash,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            self.trade_history.append(receipt)
            return receipt

    def execute_sell(self, asset: str, qty: int, price: float) -> dict:
        """Execute a paper SELL order. Returns receipt dict."""
        with self._lock:
            if asset not in self.positions or self.positions[asset]["qty"] < qty:
                available = self.positions.get(asset, {}).get("qty", 0)
                return {"status": "REJECTED", "reason": "Insufficient holdings",
                        "requested": qty, "available": available}

            proceeds = qty * price
            self.cash += proceeds

            pos = self.positions[asset]
            pnl = (price - pos["avg_price"]) * qty
            pos["qty"] -= qty

            if pos["qty"] == 0:
                del self.positions[asset]

            receipt = {
                "status": "FILLED",
                "side": "SELL",
                "asset": asset,
                "qty": qty,
                "fill_price": price,
                "proceeds": proceeds,
                "realized_pnl": round(pnl, 2),
                "cash_remaining": self.cash,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            self.trade_history.append(receipt)
            return receipt

    # ── Portfolio Queries ────────────────────────────────────────────────

    def get_portfolio_value(self, current_prices: dict) -> float:
        """Total value = cash + sum(position_value)."""
        invested = sum(
            current_prices.get(asset, pos["avg_price"]) * pos["qty"]
            for asset, pos in self.positions.items()
        )
        return round(self.cash + invested, 2)

    def get_invested_value(self, current_prices: dict = None) -> float:
        """Total capital currently invested in positions."""
        if current_prices:
            return sum(
                current_prices.get(a, p["avg_price"]) * p["qty"]
                for a, p in self.positions.items()
            )
        return sum(p["avg_price"] * p["qty"] for a, p in self.positions.items())

    def get_unrealized_pnl(self, current_prices: dict) -> float:
        """Unrealized P&L across all open positions."""
        pnl = sum(
            (current_prices.get(asset, pos["avg_price"]) - pos["avg_price"]) * pos["qty"]
            for asset, pos in self.positions.items()
        )
        return round(pnl, 2)

    def get_total_pnl(self, current_prices: dict) -> float:
        """Total P&L = portfolio_value - initial_capital."""
        return round(self.get_portfolio_value(current_prices) - self.initial_capital, 2)

    def get_daily_pnl(self, current_prices: dict) -> float:
        """P&L since the start of the current trading day."""
        return round(self.get_portfolio_value(current_prices) - self._start_of_day_value, 2)

    def get_daily_pnl_pct(self, current_prices: dict) -> float:
        """Daily P&L as percentage of start-of-day value."""
        if self._start_of_day_value == 0:
            return 0.0
        return round(self.get_daily_pnl(current_prices) / self._start_of_day_value, 4)

    def reset_daily_tracker(self, current_prices: dict):
        """Call at start of each trading day."""
        self._start_of_day_value = self.get_portfolio_value(current_prices)

    def get_position(self, asset: str) -> dict:
        """Get position details for a single asset."""
        return self.positions.get(asset, {"qty": 0, "avg_price": 0.0})

    def get_open_position_count(self) -> int:
        return len(self.positions)

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self, current_prices: dict = None) -> dict:
        """Snapshot of the entire portfolio state."""
        prices = current_prices or {}
        return {
            "cash": round(self.cash, 2),
            "positions": {a: dict(p) for a, p in self.positions.items()},
            "portfolio_value": self.get_portfolio_value(prices),
            "unrealized_pnl": self.get_unrealized_pnl(prices) if prices else 0,
            "total_pnl": self.get_total_pnl(prices) if prices else 0,
            "num_positions": self.get_open_position_count(),
            "trade_count": len(self.trade_history),
        }

    def __repr__(self) -> str:
        return (f"PaperPortfolio(cash={self.cash:.2f}, "
                f"positions={len(self.positions)}, "
                f"trades={len(self.trade_history)})")
