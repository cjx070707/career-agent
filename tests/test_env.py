import importlib
from pathlib import Path


def test_settings_load_from_dotenv_and_allow_env_override(monkeypatch) -> None:
    dotenv_path = Path(".env")
    original_content = dotenv_path.read_text(encoding="utf-8") if dotenv_path.exists() else None

    try:
        dotenv_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=from-dotenv",
                    "OPENAI_BASE_URL=https://dotenv.example/v1",
                    "DEFAULT_MODEL=dotenv-model",
                    "PLANNER_API_KEY=planner-dotenv-key",
                    "PLANNER_BASE_URL=https://planner.example/v1",
                    "PLANNER_MODEL=planner-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")

        env_module = importlib.import_module("app.env")
        env_module = importlib.reload(env_module)

        assert env_module.settings.openai_api_key == "from-dotenv"
        assert env_module.settings.openai_base_url == "https://env.example/v1"
        assert env_module.settings.default_model == "dotenv-model"
        assert env_module.settings.planner_api_key == "planner-dotenv-key"
        assert env_module.settings.planner_base_url == "https://planner.example/v1"
        assert env_module.settings.planner_model == "planner-model"
    finally:
        if original_content is None:
            dotenv_path.unlink(missing_ok=True)
        else:
            dotenv_path.write_text(original_content, encoding="utf-8")
        env_module = importlib.import_module("app.env")
        importlib.reload(env_module)
