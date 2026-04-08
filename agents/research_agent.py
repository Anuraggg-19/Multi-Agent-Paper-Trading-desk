"""
agents/research_agent.py - Enhanced Research Agent.

Listens to market ticks, accumulates OHLCV history per asset,
computes technical indicators, and uses an ML model (with rule-based
fallback) to emit BUY / SELL / HOLD signals.
"""

import asyncio
import uuid
import pandas as pd
from datetime import datetime

from models.indicators import get_latest_features
from models.signal_model import SignalModel


class ResearchAgent:
    """Analyses market data and generates trade signals."""

    # Need at least this many candles before indicators are meaningful
    MIN_HISTORY_LEN = 50

    def __init__(self, model_path: str = None):
        self.signal_model = SignalModel(model_path=model_path)
        self.price_history: dict = {}   # {asset: list of OHLCV dicts}

    # ── Main Loop (live mode) ────────────────────────────────────────────

    async def run(self, data_bus: asyncio.Queue, signal_bus: asyncio.Queue):
        """
        Listen on data_bus for market.tick events.
        Emit trade.signal on signal_bus when conditions are met.
        """
        print("  Research Agent: Online and analysing...")

        while True:
            message = await data_bus.get()

            # Pass non-tick messages through (e.g. replay_done)
            if message.get("topic") == "market.replay_done":
                await signal_bus.put(message)
                continue

            if message.get("topic") != "market.tick":
                await signal_bus.put(message)
                continue

            await self.run_single(signal_bus, message)

    # ── Process Single Tick (used by both live and backtest) ──────────

    async def run_single(self, signal_bus: asyncio.Queue, message: dict):
        """Process one market tick and optionally emit a signal."""
        asset = message["asset"]
        price = message["current_price"]

        # Accumulate candle data
        candle = {
            "timestamp": message.get("timestamp", datetime.utcnow().isoformat()),
            "open": message.get("open", price),
            "high": message.get("high", price),
            "low": message.get("low", price),
            "close": price,
            "volume": message.get("volume", 0),
        }

        if asset not in self.price_history:
            self.price_history[asset] = []

        self.price_history[asset].append(candle)

        # Cap history to prevent memory bloat (keep last 200 candles)
        if len(self.price_history[asset]) > 200:
            self.price_history[asset] = self.price_history[asset][-200:]

        # Need enough data for indicators
        if len(self.price_history[asset]) < self.MIN_HISTORY_LEN:
            # Still forward the tick so risk/execution can track prices
            await signal_bus.put(message)
            return

        # ── Compute Indicators & Predict ─────────────────────────────
        df = pd.DataFrame(self.price_history[asset])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        features = get_latest_features(df)
        if not features:
            await signal_bus.put(message)
            return

        signal_type, confidence = self.signal_model.predict(features)

        # Always forward tick so downstream sees prices
        await signal_bus.put(message)

        # Only emit actionable signals with decent confidence
        if signal_type == "HOLD" or confidence < 0.45:
            return

        # Calculate suggested quantity (~10% of 10L nominal portfolio)
        nominal_qty = max(1, int(100_000 / price)) if price > 0 else 1

        signal = {
            "topic": "trade.signal",
            "trade_id": f"tx_{uuid.uuid4().hex[:8]}",
            "agent": "research_ml_enhanced",
            "asset": asset,
            "intent": signal_type,
            "confidence": confidence,
            "current_price": price,
            "suggested_qty": nominal_qty,
            "indicators": features,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        print(
            f"\n  [Research] SIGNAL: {signal_type} {asset} | "
            f"conf={confidence:.0%} | RSI={features['rsi']} | "
            f"MACD={features['macd_histogram']} | BB={features['bb_position']}"
        )
        await signal_bus.put(signal)
