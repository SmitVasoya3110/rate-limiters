from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_ssl: bool = False
    
    rate_limit_enabled: bool = True
    default_rate_limit: int = 100
    default_rate_limit_period: int = 60
    
    environment: str = "development"
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
