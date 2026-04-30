import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# 1. 環境自動切換：判斷是在你電腦 (SQLite) 還是雲端 (PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # 修正 Zeabur/PostgreSQL 的連線網址開頭問題
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)
else:
    # 本地開發模式，建立一個名為 local.db 的 SQLite 檔案
    DB_PATH = os.path.join(os.getcwd(), "local.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. 資料表模型定義 ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    # 👑 新增密碼欄位，為了相容你之前沒有密碼的舊帳號，給定預設值 "0000"
    password = Column(String, default="0000") 
    word_sets = relationship("WordSet", back_populates="owner")
    wrong_answers = relationship("WrongAnswer", back_populates="user")

class WordSet(Base):
    __tablename__ = "word_sets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="word_sets")
    words = relationship("Word", back_populates="word_set", cascade="all, delete-orphan")

class Word(Base):
    __tablename__ = "words"
    id = Column(Integer, primary_key=True, index=True)
    english = Column(String, index=True)
    chinese = Column(String)
    part_of_speech = Column(String)
    example_sentence = Column(String, nullable=True) # 儲存 JSON 格式的例句陣列
    word_set_id = Column(Integer, ForeignKey("word_sets.id"))
    word_set = relationship("WordSet", back_populates="words")

class WrongAnswer(Base):
    __tablename__ = "wrong_answers"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    word_id = Column(Integer, ForeignKey("words.id"))
    user = relationship("User", back_populates="wrong_answers")
    word = relationship("Word")

class PracticeRecord(Base):
    __tablename__ = "practice_records"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    set_name = Column(String)  # 紀錄當時練習的題組名稱
    score = Column(String)     # 儲存格式如 "8/10"
    session_id = Column(String, nullable=True)  # 對應 AnswerLog 的 session
    created_at = Column(String, default=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    answer_logs = relationship("AnswerLog", back_populates="record", cascade="all, delete-orphan")

class AnswerLog(Base):
    __tablename__ = "answer_logs"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    record_id = Column(Integer, ForeignKey("practice_records.id"), nullable=True)
    word_id = Column(Integer, ForeignKey("words.id"))
    is_correct = Column(Integer)  # 1=答對, 0=答錯
    user_answer = Column(String, nullable=True)  # 使用者當時輸入的答案
    record = relationship("PracticeRecord", back_populates="answer_logs")
    word = relationship("Word")

# --- 3. 初始化資料庫 ---
def init_db():
    Base.metadata.create_all(bind=engine)