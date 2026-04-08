"""
agents/risk_agent.py - Risk Management Agent.

Intercepts trade.signal from Research, runs risk checks, and publishes
either trade.approved or trade.rejected before Execution sees it.

Checks:
  1. Position size  — single position <= MAX_POSITION_PCT of portfolio
  2. Max exposure   — total invested  <= MAX_EXPOSURE_PCT of capital
  3. Available cash — enough cash to cover the trade
  4. Volatility     — skip if ATR% > MAX_VOLATILITY_PCT
  5. Max positions  — no more than MAX_OPEN_POSITIONS open
  6. Daily loss     — halt if daily P&L < -MAX_DAILY_LOSS_PCT
"""

import asyncio
from datetime import datetime


class RiskAgent:
    """Gatekeeper between Research and Execution agents."""

    def __init__(self, portfolio, config):
        """
        Args:
            portfolio: core.portfolio.PaperPortfolio instance
            config:    core.config.Config class
        """
        self.portfolio = portfolio
        self.max_position_pct = config.MAX_POSITION_PCT
        self.max_exposure_pct = config.MAX_EXPOSURE_PCT
        self.max_daily_loss_pct = config.MAX_DAILY_LOSS_PCT
        self.max_open_positions = config.MAX_OPEN_POSITIONS
        self.max_volatility_pct = config.MAX_VOLATILITY_PCT

        self.current_prices: dict = {}   # updated on every market.tick
        self.stats = {"approved": 0, "rejected": 0}

    # ── Main Loop ────────────────────────────────────────────────────────

    async def run(self, signal_bus: asyncio.Queue, approved_bus: asyncio.Queue):
        """
        Listen on signal_bus for trade.signal and market.tick.
        Approved signals go to approved_bus; rejected are logged.
        """
        print("  Risk Agent: Online and guarding...")

        while True:
            message = await signal_bus.get()

            # Track latest prices for portfolio valuation
            if message.get("topic") == "market.tick":
                self.current_prices[message["asset"]] = message["current_price"]
                # Forward ticks to approved_bus so execution can also see them
                await approved_bus.put(message)
                continue

            # Forward replay_done sentinel
            if message.get("topic") == "market.replay_done":
                await approved_bus.put(message)
                continue

            # Only evaluate trade signals
            if message.get("topic") != "trade.signal":
                await approved_bus.put(message)
                continue

            # ── Run all risk checks ──────────────────────────────────
            passed, reasons = self._evaluate(message)

            if passed:
                message["topic"] = "trade.approved"
                message["risk_status"] = "APPROVED"
                self.stats["approved"] += 1
                print(f"  [Risk] APPROVED: {message['intent']} {message['asset']} "
                      f"(qty={message.get('suggested_qty','?')})")
                await approved_bus.put(message)
            else:
                message["topic"] = "trade.rejected"
                message["risk_status"] = "REJECTED"
                message["rejection_reasons"] = reasons
                self.stats["rejected"] += 1
                print(f"  [Risk] REJECTED: {message['intent']} {message['asset']} "
                      f"-> {'; '.join(reasons)}")
                # Don't put on approved_bus — signal dies here

    # ── Risk Evaluation ──────────────────────────────────────────────────

    def _evaluate(self, signal: dict) -> tuple:
        """Run all risk checks. Returns (passed: bool, reasons: list[str])."""
        reasons = []
        asset = signal.get("asset", "")
        intent = signal.get("intent", "HOLD")
        price = signal.get("current_price", 0)
        qty = signal.get("suggested_qty", 1)
        trade_value = price * qty

        # Only check buy-side risk (sells reduce risk)
        if intent == "SELL":
            # Verify we actually hold the asset
            pos = self.portfolio.get_position(asset)
            if pos["qty"] < qty:
                reasons.append(f"Cannot sell {qty}, only hold {pos['qty']}")
                return False, reasons
            return True, []

        if intent == "HOLD":
            return False, ["HOLD signal — no trade needed"]

        # ── BUY checks ───────────────────────────────────────────────

        # 1. Available cash
        ok, reason = self._check_cash(trade_value)
        if not ok:
            reasons.append(reason)

        # 2. Position size limit
        ok, reason = self._check_position_size(trade_value)
        if not ok:
            reasons.append(reason)

        # 3. Max exposure
        ok, reason = self._check_max_exposure(trade_value)
        if not ok:
            reasons.append(reason)

        # 4. Max open positions
        ok, reason = self._check_max_positions(asset)
        if not ok:
            reasons.append(reason)

        # 5. Volatility
        atr_pct = signal.get("indicators", {}).get("atr_pct", 0)
        ok, reason = self._check_volatility(atr_pct)
        if not ok:
            reasons.append(reason)

        # 6. Daily loss limit
        ok, reason = self._check_daily_loss()
        if not ok:
            reasons.append(reason)

        return len(reasons) == 0, reasons

    # ── Individual Checks ────────────────────────────────────────────────

    def _check_cash(self, trade_value: float) -> tuple:
        if trade_value > self.portfolio.cash:
            return False, (f"Insufficient cash: need Rs.{trade_value:.0f}, "
                           f"have Rs.{self.portfolio.cash:.0f}")
        return True, ""

    def _check_position_size(self, trade_value: float) -> tuple:
        portfolio_value = self.portfolio.get_portfolio_value(self.current_prices)
        max_allowed = portfolio_value * self.max_position_pct
        if trade_value > max_allowed:
            return False, (f"Position too large: Rs.{trade_value:.0f} > "
                           f"{self.max_position_pct:.0%} of portfolio (Rs.{max_allowed:.0f})")
        return True, ""

    def _check_max_exposure(self, trade_value: float) -> tuple:
        portfolio_value = self.portfolio.get_portfolio_value(self.current_prices)
        current_invested = self.portfolio.get_invested_value(self.current_prices)
        max_invested = portfolio_value * self.max_exposure_pct
        if (current_invested + trade_value) > max_invested:
            return False, (f"Max exposure breach: invested Rs.{current_invested:.0f} + "
                           f"Rs.{trade_value:.0f} > {self.max_exposure_pct:.0%} limit")
        return True, ""

    def _check_max_positions(self, asset: str) -> tuple:
        count = self.portfolio.get_open_position_count()
        # If we already hold the asset, adding to it is fine
        if asset in self.portfolio.positions:
            return True, ""
        if count >= self.max_open_positions:
            return False, (f"Max positions reached: {count}/{self.max_open_positions}")
        return True, ""

    def _check_volatility(self, atr_pct: float) -> tuple:
        if atr_pct > self.max_volatility_pct * 100:
            return False, (f"Volatility too high: ATR {atr_pct:.1f}% > "
                           f"{self.max_volatility_pct * 100:.1f}% limit")
        return True, ""

    def _check_daily_loss(self) -> tuple:
        daily_pnl_pct = self.portfolio.get_daily_pnl_pct(self.current_prices)
        if daily_pnl_pct < -self.max_daily_loss_pct:
            return False, (f"Daily loss limit hit: {daily_pnl_pct:.2%} < "
                           f"-{self.max_daily_loss_pct:.2%}")
        return True, ""
