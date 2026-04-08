"""
data/fyers_data_fetcher.py - Fyers API v3 data layer.

Two modes:
  1. Live polling  — polls quotes every N seconds, publishes market.tick events
  2. Historical replay — fetches candles and replays through the bus for backtesting
"""

import asyncio
import pandas as pd
from datetime import datetime, timedelta
from fyers_apiv3 import fyersModel


class FyersDataFetcher:
    """Fetch live + historical market data via Fyers API v3."""

    def __init__(self, client_id: str, access_token: str, symbols: list):
        self.client_id = client_id
        self.access_token = access_token
        self.symbols = symbols

        # Initialise the synchronous FyersModel client
        self.fyers = fyersModel.FyersModel(
            client_id=client_id,
            token=access_token,
            is_async=False,
            log_path="",
        )
        print(f"  Fyers client initialised for {len(symbols)} symbols")

    # ── Live Polling Mode ────────────────────────────────────────────────

    async def live_stream(self, bus: asyncio.Queue, poll_interval: int = 5):
        """
        Poll live quotes and publish market.tick events to the bus.
        Runs forever until cancelled.
        """
        symbols_csv = ",".join(self.symbols)
        print(f"  Starting live data stream: {symbols_csv}")

        while True:
            try:
                data = {"symbols": symbols_csv}
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self.fyers.quotes, data
                )

                if response.get("s") == "ok" and "d" in response:
                    for quote in response["d"]:
                        v = quote.get("v", {})
                        symbol = quote.get("n", "")

                        tick_event = {
                            "topic": "market.tick",
                            "asset": symbol,
                            "current_price": v.get("lp", 0),       # last price
                            "open": v.get("open_price", 0),
                            "high": v.get("high_price", 0),
                            "low": v.get("low_price", 0),
                            "prev_close": v.get("prev_close_price", 0),
                            "volume": v.get("volume", 0),
                            "change_pct": v.get("ch", 0),
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                        print(f"  [Market] {symbol}: Rs.{tick_event['current_price']}")
                        await bus.put(tick_event)
                else:
                    code = response.get("code", "?")
                    msg = response.get("message", str(response))
                    print(f"  [Market] Quotes error ({code}): {msg}")

            except Exception as e:
                print(f"  [Market] Polling error: {e}")

            await asyncio.sleep(poll_interval)

    # ── Historical Data ──────────────────────────────────────────────────

    def fetch_historical(
        self,
        symbol: str,
        resolution: str = "5",
        from_date: str = None,
        to_date: str = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles from Fyers history API.

        Args:
            symbol:     e.g. "NSE:RELIANCE-EQ"
            resolution: "1","5","15","30","60","1D" etc.
            from_date:  "yyyy-mm-dd"  (defaults to 30 days ago)
            to_date:    "yyyy-mm-dd"  (defaults to today)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if to_date is None:
            to_date = datetime.now().strftime("%Y-%m-%d")

        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": from_date,
            "range_to": to_date,
            "cont_flag": "1",
        }

        response = self.fyers.history(data=data)

        if response.get("s") != "ok" or "candles" not in response:
            print(f"  [History] Error for {symbol}: {response.get('message', response)}")
            return pd.DataFrame()

        candles = response["candles"]
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df["symbol"] = symbol
        return df

    # ── Historical Replay for Backtesting ────────────────────────────────

    async def replay_historical(
        self,
        bus: asyncio.Queue,
        symbol: str,
        resolution: str = "5",
        from_date: str = None,
        to_date: str = None,
        speed: float = 0.0,
    ):
        """
        Replay historical candles through the message bus as market.tick events.
        speed=0 means instant replay, speed=1 means ~1 second per candle.
        """
        df = await asyncio.get_event_loop().run_in_executor(
            None, self.fetch_historical, symbol, resolution, from_date, to_date
        )

        if df.empty:
            print(f"  [Replay] No data for {symbol}")
            return df

        print(f"  [Replay] Replaying {len(df)} candles for {symbol}")

        for _, row in df.iterrows():
            tick_event = {
                "topic": "market.tick",
                "asset": symbol,
                "current_price": float(row["close"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": int(row["volume"]),
                "prev_close": float(row["close"]),  # approx
                "timestamp": row["timestamp"].isoformat() + "Z",
            }
            await bus.put(tick_event)

            if speed > 0:
                await asyncio.sleep(speed)

        # End-of-replay sentinel
        await bus.put({"topic": "market.replay_done", "asset": symbol})
        return df

    # ── Utility Methods ──────────────────────────────────────────────────

    def get_quotes(self, symbols: list = None) -> dict:
        """Fetch real-time quotes. Returns raw API response."""
        syms = symbols or self.symbols
        data = {"symbols": ",".join(syms)}
        return self.fyers.quotes(data=data)

    def get_funds(self) -> dict:
        """Fetch account fund details."""
        return self.fyers.funds()

    def get_positions(self) -> dict:
        """Fetch open positions."""
        return self.fyers.positions()

    def get_market_depth(self, symbol: str) -> dict:
        """Fetch market depth for a symbol."""
        data = {"symbol": symbol, "ohlcv_flag": "1"}
        return self.fyers.depth(data=data)

    def get_profile(self) -> dict:
        """Fetch user profile to verify connection."""
        return self.fyers.get_profile()
