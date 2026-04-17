import csv, json, httpx
from fastapi import FastAPI, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.responses import FileResponse
from deep_translator import GoogleTranslator
import database as db

app = FastAPI()
db.init_db()
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    session = db.SessionLocal()
    try: yield session
    finally: session.close()

# --- 新增的 API：檢查是否有錯題 ---
@app.get("/users/{user_id}/has_wrong")
def has_wrong(user_id: int, dbs: Session = Depends(get_db)):
    exists = dbs.query(db.WrongAnswer).filter_by(user_id=user_id).first()
    return {"has_wrong": exists is not None}

# --- 新增的 API：取得練習紀錄 ---
@app.get("/records/{user_id}")
def get_records(user_id: int, dbs: Session = Depends(get_db)):
    return dbs.query(db.PracticeRecord).filter_by(user_id=user_id).order_by(db.PracticeRecord.id.desc()).limit(10).all()

# --- 新增的 API：提交練習紀錄 ---
@app.post("/submit_record")
def submit_record(user_id: int = Form(...), set_name: str = Form(...), score: str = Form(...), dbs: Session = Depends(get_db)):
    record = db.PracticeRecord(user_id=user_id, set_name=set_name, score=score)
    dbs.add(record)
    dbs.commit()
    return {"status": "success"}

# --- 其餘原有 API ---
@app.post("/login")
def login(username: str = Form(...), dbs: Session = Depends(get_db)):
    user = dbs.query(db.User).filter_by(username=username).first()
    if not user:
        user = db.User(username=username)
        dbs.add(user); dbs.commit(); dbs.refresh(user)
    return {"user_id": user.id, "username": user.username}

@app.get("/users/{user_id}/sets")
def get_user_sets(user_id: int, dbs: Session = Depends(get_db)):
    return dbs.query(db.WordSet).filter_by(owner_id=user_id).all()

@app.get("/wrong_answers/{user_id}")
def get_wrong_answers(user_id: int, dbs: Session = Depends(get_db)):
    wrong_records = dbs.query(db.WrongAnswer).filter_by(user_id=user_id).all()
    return [r.word for r in wrong_records]

@app.get("/quiz/{set_id}")
def get_quiz(set_id: int, dbs: Session = Depends(get_db)):
    return dbs.query(db.Word).filter_by(word_set_id=set_id).all()

@app.post("/submit_answer")
def submit_answer(user_id: int = Form(...), word_id: int = Form(...), is_correct: bool = Form(...), dbs: Session = Depends(get_db)):
    if not is_correct:
        if not dbs.query(db.WrongAnswer).filter_by(user_id=user_id, word_id=word_id).first():
            dbs.add(db.WrongAnswer(user_id=user_id, word_id=word_id))
            dbs.commit()
    return {"status": "recorded"}

async def fetch_example_sentence(word: str):
    examples = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
            if resp.status_code == 200:
                data = resp.json()
                raw_exs = []
                for entry in data:
                    for m in entry.get("meanings", []):
                        for d in m.get("definitions", []):
                            if d.get("example"): raw_exs.append(d["example"])
                            if len(raw_exs) >= 2: break
                gt = GoogleTranslator(source='en', target='zh-TW')
                for ex in raw_exs:
                    examples.append({"en": ex, "zh": gt.translate(ex)})
    except: pass
    if not examples: examples = [{"en": f"I know the word {word}.", "zh": f"我認識 {word} 這個單字。"}]
    return json.dumps(examples)

@app.post("/upload_csv/{user_id}")
async def upload_csv(user_id: int, set_name: str = Form(...), file: UploadFile = File(...), dbs: Session = Depends(get_db)):
    try:
        new_set = db.WordSet(name=set_name, owner_id=user_id)
        dbs.add(new_set)
        dbs.commit()
        dbs.refresh(new_set)
        
        # 關鍵修正：使用 utf-8-sig 自動移除 Excel 隱藏字元
        content = (await file.read()).decode('utf-8-sig').splitlines()
        reader = csv.DictReader(content)
        
        for row in reader:
            word = row.get('word', '').strip()
            if not word:
                continue # 如果遇到空白行就跳過
                
            # 為了確保不會卡住，我們依然先用測試版例句
            default_ex = json.dumps([{"en": f"I am learning the word {word}.", "zh": f"我正在學習 {word} 這個單字。"}])
            
            w = db.Word(
                english=word, 
                part_of_speech=row.get('pos', '').strip(), 
                chinese=row.get('chinese', '').strip(), 
                example_sentence=default_ex, 
                word_set_id=new_set.id
            )
            dbs.add(w)
            
        dbs.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"上傳發生錯誤: {e}") # 會印在終端機裡
        return {"status": "error", "message": str(e)}

@app.get("/")
def read_index(): return FileResponse("static/index.html")