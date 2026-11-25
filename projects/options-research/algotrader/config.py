from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ResearchConfig:
    initial_cash: float = 1000.0
    start: str = "2016-01-01"
    end: str = ""
    cache_dir: str = "data/cache"
    report_dir: str = "reports"
    refresh_data: bool = False
    benchmark: str = "SPY"
    risk_free_rate: float = 0.0
    tickers: List[str] = field(
        default_factory=lambda: [
            "SPY",
            "QQQ",
            "IWM",
            "DIA",
            "XLK",
            "XLF",
            "XLE",
            "XLY",
            "XLV",
            "GLD",
            "TLT",
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "META",
            "GOOGL",
            "TSLA",
        ]
    )
    market_ticker: str = "SPY"
    vix_ticker: str = "^VIX"


@dataclass(frozen=True)
class ModelConfig:
    min_train_days: int = 504
    train_window_days: int = 756
    retrain_every_days: int = 21
    l2: float = 2.0
    epochs: int = 350
    learning_rate: float = 0.04
    probability_floor: float = 0.50
    target_name: str = "target_up"


@dataclass(frozen=True)
class StrategyConfig:
    max_positions: int = 3
    max_position_weight: float = 0.35
    max_gross_exposure: float = 1.25
    risk_off_gross_exposure: float = 0.25
    volatility_target: float = 0.25
    signal_threshold: float = 0.02
    vix_risk_off_level: float = 30.0
    trend_sma_days: int = 200
    transaction_cost_bps: float = 8.0
    drawdown_stop: float = 0.25
    cooldown_days: int = 21
    monthly_loss_stop: float = 0.0
    monthly_profit_lock: float = 0.0
    allow_fractional_shares: bool = True
