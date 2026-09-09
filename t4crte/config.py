import os
import json
import shutil
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class TradingConfig:
    # 1. Exchange & Trading Mode
    exchange_id: str = "bybit"  # "bybit", "binance", "mexc", "kucoin", "gateio", "okx"
    is_paper_trading: bool = True  # True = Paper simulation, False = Real money execution
    
    # Capital and Trade Sizing
    initial_balance: float = 4.0  # $4.00 starting capital
    trade_amount_usdt: float = 2.0  # Max per trade (e.g. $2.00 or $4.00)
    max_open_trades: int = 2  # Max simultaneous positions
    paper_fee_pct: float = 0.1  # Paper simulation fee %
    paper_slippage_pct: float = 0.05  # Paper simulation slippage %
    
    # Trading Pairs & Timeframe
    monitored_pairs: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = "15m"
    
    # Strategy & Risk Management
    rsi_oversold: float = 35.0
    rsi_overbought: float = 68.0
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    ema_baseline: int = 200
    bollinger_period: int = 20
    bollinger_std_dev: float = 2.0
    take_profit_pct: float = 1.8  # Target profit +1.8%
    stop_loss_pct: float = 1.2  # Max initial loss allowed -1.2%
    trailing_stop_activation_pct: float = 0.8  # Activate trailing stop when profit hits +0.8%
    trailing_stop_callback_pct: float = 0.4  # Lock profits if price pulls back 0.4% from peak
    
    # 2. Exchange API Keys
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""  # Required for some exchanges like KuCoin/OKX
    
    # 3. Universal AI Configuration
    # Supported: "quant_builtin", "deepseek", "openrouter", "groq", "openai", "gemini", "anthropic", "custom"
    ai_provider: str = "quant_builtin"
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_api_key: str = ""
    ai_model: str = "deepseek-chat"
    ai_temperature: float = 0.2
    
    # 4. Background Autonomous Worker
    auto_trading_enabled: bool = False
    worker_interval_seconds: int = 15
    
    # 5. Telegram Notifications & Security
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dashboard_password: str = ""
    dashboard_password_hash: str = ""
    
    # Database & Config Paths
    db_path: str = os.path.join(os.path.dirname(__file__), "trading_data.db")
    config_file: str = os.path.join(os.path.dirname(__file__), "config.json")
    example_config_file: str = os.path.join(os.path.dirname(__file__), "config.example.json")

    def save_to_json(self):
        """Save settings to config.json"""
        data = {
            "exchange_id": self.exchange_id,
            "is_paper_trading": self.is_paper_trading,
            "initial_balance": self.initial_balance,
            "trade_amount_usdt": self.trade_amount_usdt,
            "max_open_trades": self.max_open_trades,
            "paper_fee_pct": self.paper_fee_pct,
            "paper_slippage_pct": self.paper_slippage_pct,
            "monitored_pairs": self.monitored_pairs,
            "timeframe": self.timeframe,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_trend": self.ema_trend,
            "ema_baseline": self.ema_baseline,
            "bollinger_period": self.bollinger_period,
            "bollinger_std_dev": self.bollinger_std_dev,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trailing_stop_activation_pct": self.trailing_stop_activation_pct,
            "trailing_stop_callback_pct": self.trailing_stop_callback_pct,
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "api_passphrase": self.api_passphrase,
            "ai_provider": self.ai_provider,
            "ai_base_url": self.ai_base_url,
            "ai_api_key": self.ai_api_key,
            "ai_model": self.ai_model,
            "ai_temperature": self.ai_temperature,
            "auto_trading_enabled": self.auto_trading_enabled,
            "worker_interval_seconds": self.worker_interval_seconds,
            "telegram_enabled": self.telegram_enabled,
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "dashboard_password": self.dashboard_password,
            "dashboard_password_hash": self.dashboard_password_hash,
        }

        # Do not save sensitive values if they come from environment variables
        if os.environ.get("T4_API_KEY") or os.environ.get("TRADING_API_KEY"):
            data["api_key"] = ""
        if os.environ.get("T4_API_SECRET") or os.environ.get("TRADING_API_SECRET"):
            data["api_secret"] = ""
        if os.environ.get("T4_API_PASSPHRASE") or os.environ.get("TRADING_API_PASSPHRASE"):
            data["api_passphrase"] = ""
        if os.environ.get("T4_AI_API_KEY") or os.environ.get("AI_API_KEY"):
            data["ai_api_key"] = ""
        if os.environ.get("T4_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN"):
            data["telegram_bot_token"] = ""
        if os.environ.get("T4_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID"):
            data["telegram_chat_id"] = ""
        if os.environ.get("T4_DASHBOARD_PASSWORD") or os.environ.get("DASHBOARD_PASSWORD"):
            data["dashboard_password"] = ""
        if os.environ.get("T4_DASHBOARD_PASSWORD_HASH") or os.environ.get("DASHBOARD_PASSWORD_HASH"):
            data["dashboard_password_hash"] = ""

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    @classmethod
    def load_from_json(cls) -> "TradingConfig":
        """Load settings from config.json if exists, otherwise config.example.json or defaults"""
        load_dotenv()
        cfg = cls()

        target_file = cfg.config_file
        if not os.path.exists(target_file):
            if os.path.exists(cfg.example_config_file):
                try:
                    shutil.copyfile(cfg.example_config_file, target_file)
                except Exception:
                    target_file = cfg.example_config_file

        if os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if hasattr(cfg, k):
                            setattr(cfg, k, v)
            except Exception:
                pass

        # Load sensitive keys from environment variables (.env / os.environ) if available
        env_api_key = (os.environ.get('T4_API_KEY') or os.environ.get('TRADING_API_KEY', '')).strip()
        env_api_secret = (os.environ.get('T4_API_SECRET') or os.environ.get('TRADING_API_SECRET', '')).strip()
        env_api_pass = (os.environ.get('T4_API_PASSPHRASE') or os.environ.get('TRADING_API_PASSPHRASE', '')).strip()
        env_ai_api_key = (os.environ.get('T4_AI_API_KEY') or os.environ.get('AI_API_KEY', '')).strip()
        env_tg_token = (os.environ.get('T4_TELEGRAM_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')).strip()
        env_tg_chat = (os.environ.get('T4_TELEGRAM_CHAT_ID') or os.environ.get('TELEGRAM_CHAT_ID', '')).strip()
        env_pwd = (os.environ.get('T4_DASHBOARD_PASSWORD') or os.environ.get('DASHBOARD_PASSWORD', '')).strip()
        env_pwd_hash = (os.environ.get('T4_DASHBOARD_PASSWORD_HASH') or os.environ.get('DASHBOARD_PASSWORD_HASH', '')).strip()

        if env_api_key:
            cfg.api_key = env_api_key
        if env_api_secret:
            cfg.api_secret = env_api_secret
        if env_api_pass:
            cfg.api_passphrase = env_api_pass
        if env_ai_api_key:
            cfg.ai_api_key = env_ai_api_key
        if env_tg_token:
            cfg.telegram_bot_token = env_tg_token
        if env_tg_chat:
            cfg.telegram_chat_id = env_tg_chat
        if env_pwd:
            cfg.dashboard_password = env_pwd
        if env_pwd_hash:
            cfg.dashboard_password_hash = env_pwd_hash

        return cfg

config = TradingConfig.load_from_json()
