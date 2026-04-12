from app.db.session import init_db
from app.services.memory_service import MemoryService


def test_memory_service_persists_turns_across_instances(tmp_path) -> None:
    db_path = tmp_path / "test_memory.db"
    init_db(str(db_path))

    writer = MemoryService(db_path=str(db_path), max_turns=6)
    writer.save_turn("user-1", "hello", "hi there")

    reader = MemoryService(db_path=str(db_path), max_turns=6)
    turns = reader.load_recent_messages("user-1")

    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "hello"
    assert turns[1].role == "assistant"
    assert turns[1].content == "hi there"


def test_memory_service_keeps_only_recent_turns(tmp_path) -> None:
    db_path = tmp_path / "test_memory_trim.db"
    init_db(str(db_path))

    service = MemoryService(db_path=str(db_path), max_turns=4)
    service.save_turn("user-1", "one", "A")
    service.save_turn("user-1", "two", "B")
    service.save_turn("user-1", "three", "C")

    turns = service.load_recent_messages("user-1")

    assert [turn.content for turn in turns] == ["two", "B", "three", "C"]
