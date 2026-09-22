from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fixam:fixam@localhost:5432/fixam"
    database_url_sync: str = "postgresql://fixam:fixam@localhost:5432/fixam"

    model_config = {"env_prefix": "FIXAM_"}


settings = Settings()
