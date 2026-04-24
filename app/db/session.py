import sqlite3
from sqlite3 import Connection
from typing import Optional

from app.db.base import resolve_db_path


def get_database_url(db_path: Optional[str] = None) -> str:
    return f"sqlite:///{resolve_db_path(db_path)}"


def get_connection(db_path: Optional[str] = None) -> Connection:
    connection = sqlite3.connect(resolve_db_path(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Optional[str] = None) -> None:
    with get_connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                user_id TEXT
            );

            CREATE TABLE IF NOT EXISTS job_postings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                version TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id)
            );

            CREATE TABLE IF NOT EXISTS career_profiles (
                user_id TEXT PRIMARY KEY,
                target_role_preference TEXT NOT NULL DEFAULT '',
                skill_keywords TEXT NOT NULL DEFAULT '',
                career_focus_notes TEXT NOT NULL DEFAULT '',
                application_patterns TEXT NOT NULL DEFAULT '',
                interview_weaknesses TEXT NOT NULL DEFAULT '',
                next_focus_areas TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                company TEXT NOT NULL,
                job_title TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id)
            );

            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                company TEXT NOT NULL,
                job_title TEXT NOT NULL,
                interview_round TEXT NOT NULL,
                result TEXT NOT NULL,
                feedback TEXT NOT NULL DEFAULT '',
                interviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id)
            );
            """
        )
        candidate_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(candidates)").fetchall()
        }
        if "user_id" not in candidate_columns:
            connection.execute("ALTER TABLE candidates ADD COLUMN user_id TEXT")
        career_profile_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(career_profiles)").fetchall()
        }
        for column in (
            "application_patterns",
            "interview_weaknesses",
            "next_focus_areas",
        ):
            if column not in career_profile_columns:
                connection.execute(
                    f"ALTER TABLE career_profiles ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
