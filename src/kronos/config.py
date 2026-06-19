import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class DatabaseConfig:
    url: str = "sqlite:///storage/kronos.db"

@dataclass
class BrokerConfig:
    name: str = "fyers"
    client_id: str = ""
    secret: str = ""

@dataclass
class KronosConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    model_path: str = "storage/models/kronos_latest.pt"

def load_config() -> KronosConfig:
    env = os.getenv("APP_ENV", "dev")
    config = KronosConfig()
    
    # Simple loader logic to be expanded later
    config_dir = Path(__file__).parent.parent.parent / "config"
    
    def update_from_yaml(filepath):
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f) or {}
                if 'db' in data and 'url' in data['db']:
                    config.db.url = data['db']['url']
                if 'broker' in data:
                    config.broker.name = data['broker'].get('name', config.broker.name)
                    config.broker.client_id = data['broker'].get('client_id', config.broker.client_id)
                if 'model_path' in data:
                    config.model_path = data['model_path']

    # Load defaults
    update_from_yaml(config_dir / "default.yaml")
    
    # Load environment specific config
    update_from_yaml(config_dir / f"{env}.yaml")
    
    # Environment variables override (example)
    if db_url := os.getenv("DATABASE_URL"):
        config.db.url = db_url
        
    return config
