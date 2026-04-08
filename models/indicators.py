"""
models/indicators.py - Technical indicator computations.
Pure functions operating on pandas DataFrames with OHLCV columns.
"""

import numpy as np
import pandas as pd


def compute_rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.Series:
    """Relative Strength Index (RSI)."""
    delta = df[column].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = "close",
) -> dict:
    """MACD line, signal line, and histogram."""
    ema_fast = df[column].ewm(span=fast, adjust=False).mean()
    ema_slow = df[column].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
    }


def compute_bollinger_bands(
    df: pd.DataFrame, period: int = 20, num_std: float = 2.0, column: str = "close"
) -> dict:
    """Bollinger Bands: upper, middle (SMA), lower."""
    sma = df[column].rolling(window=period).mean()
    std = df[column].rolling(window=period).std()
    return {
        "upper": sma + num_std * std,
        "middle": sma,
        "lower": sma - num_std * std,
    }


def compute_sma(df: pd.DataFrame, fast: int = 20, slow: int = 50, column: str = "close") -> dict:
    """Simple Moving Averages - fast and slow."""
    return {
        "sma_fast": df[column].rolling(window=fast).mean(),
        "sma_slow": df[column].rolling(window=slow).mean(),
    }


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — volatility measure."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume vs average volume ratio."""
    avg_vol = df["volume"].rolling(window=period).mean()
    return (df["volume"] / avg_vol.replace(0, np.nan)).fillna(1.0)


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ALL indicator columns to a copy of the input DataFrame.
    Expects columns: open, high, low, close, volume
    """
    out = df.copy()

    # RSI
    out["rsi"] = compute_rsi(out)

    # MACD
    macd = compute_macd(out)
    out["macd_line"] = macd["macd_line"]
    out["macd_signal"] = macd["signal_line"]
    out["macd_histogram"] = macd["histogram"]

    # Bollinger Bands
    bb = compute_bollinger_bands(out)
    out["bb_upper"] = bb["upper"]
    out["bb_middle"] = bb["middle"]
    out["bb_lower"] = bb["lower"]

    # SMA crossover
    smas = compute_sma(out)
    out["sma_fast"] = smas["sma_fast"]
    out["sma_slow"] = smas["sma_slow"]
    out["sma_crossover"] = (out["sma_fast"] > out["sma_slow"]).astype(int)

    # ATR
    out["atr"] = compute_atr(out)

    # Volume ratio
    out["volume_ratio"] = compute_volume_ratio(out)

    return out


def get_bb_position(price: float, upper: float, lower: float) -> str:
    """Classify price position relative to Bollinger Bands."""
    if np.isnan(upper) or np.isnan(lower):
        return "middle"
    band_range = upper - lower
    if band_range == 0:
        return "middle"
    position = (price - lower) / band_range
    if position <= 0.2:
        return "lower"
    elif position >= 0.8:
        return "upper"
    return "middle"


def get_latest_features(df: pd.DataFrame) -> dict:
    """
    Extract the most recent indicator values as a flat dict.
    Useful for feeding into the ML model or logging.
    """
    if df.empty:
        return {}

    enriched = compute_all_indicators(df)
    last = enriched.iloc[-1]

    return {
        "rsi": round(float(last.get("rsi", 50)), 2),
        "macd_histogram": round(float(last.get("macd_histogram", 0)), 4),
        "bb_position": get_bb_position(
            float(last["close"]),
            float(last.get("bb_upper", last["close"])),
            float(last.get("bb_lower", last["close"])),
        ),
        "sma_crossover": "bullish" if last.get("sma_crossover", 0) == 1 else "bearish",
        "atr": round(float(last.get("atr", 0)), 2),
        "atr_pct": round(float(last.get("atr", 0)) / float(last["close"]) * 100, 2)
            if last["close"] != 0 else 0,
        "volume_ratio": round(float(last.get("volume_ratio", 1)), 2),
        "close": round(float(last["close"]), 2),
    }
