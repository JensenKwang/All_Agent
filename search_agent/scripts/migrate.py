"""
기존 news_data.db에 새 컬럼을 추가하는 마이그레이션 스크립트.
SQLite는 ALTER TABLE ADD COLUMN만 지원하므로 직접 실행.
이미 컬럼이 있으면 에러를 무시하고 넘어감.
"""
import sqlite3

DB_PATH = "news_data.db"

MIGRATIONS = [
    ("reporter", "reporter_score", "INTEGER DEFAULT 50"),
    ("news",     "source_type",    "TEXT"),
    ("news",     "sentiment_score","INTEGER"),
]

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for table, column, col_def in MIGRATIONS:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            print(f"[OK] {table}.{column} 추가 완료")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"[SKIP] {table}.{column} 이미 존재")
            else:
                raise

    conn.commit()
    conn.close()
    print("마이그레이션 완료")

if __name__ == "__main__":
    run()
