from pathlib import Path


def test_isolated_runtime_uses_temp_paths(isolated_runtime) -> None:
    runtime = isolated_runtime
    project_data_dir = Path(__file__).resolve().parents[1] / "data"

    assert runtime["db_path"].parent != project_data_dir
    assert project_data_dir not in runtime["db_path"].parents
    assert project_data_dir not in runtime["chroma_path"].parents
