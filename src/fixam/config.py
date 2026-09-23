from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fixam:fixam@localhost:5432/fixam"
    database_url_sync: str = "postgresql://fixam:fixam@localhost:5432/fixam"
    whatsapp_app_secret: str = ""
    webhook_verify_token: str = "test-verify-token"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""

    momo_base_url: str = "https://sandbox.momodeveloper.mtn.com"
    momo_subscription_key: str = ""
    momo_api_user: str = ""
    momo_api_key: str = ""
    momo_callback_host: str = ""

    model_config = {"env_prefix": "FIXAM_"}


settings = Settings()
