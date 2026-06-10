from pathlib import Path

from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://aiva:aiva@localhost:5432/ai_visibility_audit"

    # Chat completions run on Gemini via its OpenAI-compatible endpoint.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # OpenAI is used only for query embeddings (the WildChat corpus is
    # pre-embedded with text-embedding-3-small). Optional — leave blank to
    # disable the WildChat similarity stage.
    openai_api_key: str = ""

    exa_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    brightdata_api_key: str = ""
    brightdata_chatgpt_dataset_id: str = "gd_m7aof0k82r803d5bjm"
    brightdata_gemini_dataset_id: str = ""
    brightdata_google_ai_mode_dataset_id: str = ""
    api_key: str = "change-me-to-a-random-string"
    app_env: str = "development"

    cors_origins: str = "http://localhost:5173"
    report_render_url: str = "http://web"
    report_render_extra_wait_ms: int = 800

    query_gen_model: str = "gemini-3.5-flash"
    query_profile_model: str = "gemini-3.1-flash-lite"
    sentiment_model: str = "gemini-3.1-flash-lite"

    model_config = {"env_file": [".env", str(ROOT_DIR / ".env")], "extra": "ignore"}


settings = Settings()
