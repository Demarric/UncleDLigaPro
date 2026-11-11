
import sqlite3

def connect_db():
    return sqlite3.connect("liga_pro.db")


def create_tables():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1 TEXT NOT NULL,
        player2 TEXT NOT NULL,
        winner TEXT NOT NULL,
        match_date TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1 TEXT NOT NULL,
        player2 TEXT NOT NULL,
        probability1 REAL NOT NULL,
        probability2 REAL NOT NULL,
        predicted_winner TEXT NOT NULL,
        prediction_date TEXT NOT NULL,
        actual_winner TEXT,
        evaluated INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    print("Liga Pro database upgraded successfully!")
