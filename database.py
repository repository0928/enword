import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Zeabur 會提供 DATABASE_URL 環境變數
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/worddb")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 使用者資料表
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True) # 登入用的用戶名
    
    word_sets = relationship("WordSet", back_populates="owner")
    wrong_answers = relationship("WrongAnswer", back_populates="user")

# 題組資料表
class WordSet(Base):
    __tablename__ = "word_sets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="word_sets")
    words = relationship("Word", back_populates="word_set", cascade="all, delete-orphan")

# 單字資料表
class Word(Base):
    __tablename__ = "words"
    id = Column(Integer, primary_key=True, index=True)
    english = Column(String, index=True)
    chinese = Column(String)
    part_of_speech = Column(String) # 詞性
    example_sentence = Column(String, nullable=True) # 例句
    word_set_id = Column(Integer, ForeignKey("word_sets.id"))

    word_set = relationship("WordSet", back_populates="words")

# 錯題紀錄表
class WrongAnswer(Base):
    __tablename__ = "wrong_answers"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    word_id = Column(Integer, ForeignKey("words.id"))

    user = relationship("User", back_populates="wrong_answers")
    word = relationship("Word")

# 建立所有資料表
def init_db():
    Base.metadata.create_all(bind=engine)