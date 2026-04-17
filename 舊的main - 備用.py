import csv
import io
import httpx
from typing import List
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

import database as db

# 1. 先建立 app 物件
app = FastAPI(title="Junior High English Vocab")

# 2. 初始化資料庫與掛載路徑
db.init_db()
app.mount("/static", StaticFiles(directory="static"), name="static")

# 取得資料庫連線的工具
def get_db():
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()

# --- 3. 之後才能開始定義這些 @app 的功能 ---

@app.post("/login")
def login(username: str = Form(...), dbs: Session = Depends(get_db)):
    user = dbs.query(db.User).filter(db.User.username == username).first()
    if not user:
        user = db.User(username=username)
        dbs.add(user)
        dbs.commit()
        dbs.refresh(user)
    return {"user_id": user.id, "username": user.username}

@app.get("/users/{user_id}/sets")
def get_user_sets(user_id: int, dbs: Session = Depends(get_db)):
    sets = dbs.query(db.WordSet).filter(db.WordSet.owner_id == user_id).all()
    return sets

@app.post("/upload_csv/{user_id}")
async def upload_csv(user_id: int, set_name: str = Form(...), file: UploadFile = File(...), dbs: Session = Depends(get_db)):
    new_set = db.WordSet(name=set_name, owner_id=user_id)
    dbs.add(new_set)
    dbs.commit()
    dbs.refresh(new_set)

    content = await file.read()
    decoded = content.decode('utf-8').splitlines()
    reader = csv.DictReader(decoded)

    for row in reader:
        example = await fetch_example_sentence(row['word'])
        new_word = db.Word(
            english=row['word'],
            part_of_speech=row['pos'],
            chinese=row['chinese'],
            example_sentence=example,
            word_set_id=new_set.id
        )
        dbs.add(new_word)
    dbs.commit()
    return {"message": "success"}

async def fetch_example_sentence(word: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
            if response.status_code == 200:
                data = response.json()
                meanings = data[0].get("meanings", [])
                for m in meanings:
                    for d in m.get("definitions", []):
                        if d.get("example"): return d.get("example")
    except: pass
    return "No example available."

@app.get("/quiz/{set_id}")
def get_quiz(set_id: int, dbs: Session = Depends(get_db)):
    return dbs.query(db.Word).filter(db.Word.word_set_id == set_id).all()

@app.post("/submit_answer")
def submit_answer(user_id: int = Form(...), word_id: int = Form(...), is_correct: bool = Form(...), dbs: Session = Depends(get_db)):
    if not is_correct:
        exists = dbs.query(db.WrongAnswer).filter_by(user_id=user_id, word_id=word_id).first()
        if not exists:
            wrong = db.WrongAnswer(user_id=user_id, word_id=word_id)
            dbs.add(wrong)
            dbs.commit()
    return {"status": "recorded"}

@app.get("/")
def read_index():
    return FileResponse("static/index.html")