from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fixam:fixam@localhost:5432/fixam"
    database_url_sync: str = "postgresql://fixam:fixam@localhost:5432/fixam"
    whatsapp_app_secret: str = ""
    webhook_verify_token: str = "test-verify-token"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""

    model_config = {"env_prefix": "FIXAM_"}


settings = Settings()
