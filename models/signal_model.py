"""
models/signal_model.py - ML-based trade signal classifier.

Uses a Random Forest to predict BUY / SELL / HOLD from technical indicators.
Falls back to a rule-based strategy until trained on enough data.
"""

import os
import pickle
import numpy as np


class SignalModel:
    """Lightweight ML signal classifier with rule-based fallback."""

    LABELS = ["HOLD", "BUY", "SELL"]

    def __init__(self, model_path: str = None):
        self.model = None
        self.is_trained = False
        self.model_path = model_path

        if model_path and os.path.exists(model_path):
            self.load_model(model_path)

    # ── Rule-Based Fallback ──────────────────────────────────────────────

    def rule_based_predict(self, features: dict) -> tuple:
        """
        Simple rule-based signal when ML model is not trained.
        Returns (signal, confidence).
        """
        score = 0.0

        # RSI signal
        rsi = features.get("rsi", 50)
        if rsi < 30:
            score += 2.0    # oversold -> buy signal
        elif rsi < 40:
            score += 1.0
        elif rsi > 70:
            score -= 2.0    # overbought -> sell signal
        elif rsi > 60:
            score -= 1.0

        # MACD histogram
        macd_hist = features.get("macd_histogram", 0)
        if macd_hist > 0:
            score += 1.0
        elif macd_hist < 0:
            score -= 1.0

        # Bollinger Band position
        bb_pos = features.get("bb_position", "middle")
        if bb_pos == "lower":
            score += 1.5     # near lower band -> buy
        elif bb_pos == "upper":
            score -= 1.5     # near upper band -> sell

        # SMA crossover
        sma_cross = features.get("sma_crossover", "bearish")
        if sma_cross == "bullish":
            score += 1.0
        else:
            score -= 1.0

        # Volume surge amplifies signal
        vol_ratio = features.get("volume_ratio", 1.0)
        if vol_ratio > 1.5:
            score *= 1.3

        # Decide
        max_possible = 7.0
        confidence = min(abs(score) / max_possible, 0.95)

        if score >= 2.0:
            return "BUY", round(confidence, 2)
        elif score <= -2.0:
            return "SELL", round(confidence, 2)
        else:
            return "HOLD", round(0.5 + confidence * 0.2, 2)

    # ── ML Prediction ────────────────────────────────────────────────────

    def predict(self, features: dict) -> tuple:
        """
        Predict signal from feature dict.
        Uses ML model if trained, otherwise rule-based fallback.
        Returns (signal: str, confidence: float).
        """
        if not self.is_trained or self.model is None:
            return self.rule_based_predict(features)

        feature_vector = self._features_to_array(features)
        proba = self.model.predict_proba(feature_vector.reshape(1, -1))[0]
        predicted_idx = np.argmax(proba)
        confidence = float(proba[predicted_idx])

        return self.LABELS[predicted_idx], round(confidence, 2)

    # ── Training ─────────────────────────────────────────────────────────

    def train(self, X: np.ndarray, y: np.ndarray):
        """
        Train the Random Forest on labeled feature data.
        X: shape (n_samples, n_features)
        y: shape (n_samples,) with values 0=HOLD, 1=BUY, 2=SELL
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(X_train, y_train)
        self.is_trained = True

        accuracy = self.model.score(X_test, y_test)
        print(f"   ML Model trained — accuracy: {accuracy:.2%} on test set")
        return accuracy

    # ── Persistence ──────────────────────────────────────────────────────

    def save_model(self, path: str):
        if self.model is not None:
            with open(path, "wb") as f:
                pickle.dump(self.model, f)
            print(f"   Model saved to {path}")

    def load_model(self, path: str):
        if os.path.exists(path):
            with open(path, "rb") as f:
                self.model = pickle.load(f)
            self.is_trained = True
            print(f"   ML model loaded from {path}")

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _features_to_array(features: dict) -> np.ndarray:
        """Convert feature dict to numpy array in consistent order."""
        bb_map = {"lower": -1, "middle": 0, "upper": 1}
        sma_map = {"bearish": 0, "bullish": 1}

        return np.array([
            features.get("rsi", 50),
            features.get("macd_histogram", 0),
            bb_map.get(features.get("bb_position", "middle"), 0),
            sma_map.get(features.get("sma_crossover", "bearish"), 0),
            features.get("atr", 0),
            features.get("volume_ratio", 1.0),
        ], dtype=np.float64)
