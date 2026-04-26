import csv, json, httpx
from fastapi import FastAPI, Depends, UploadFile, File, Form, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette.responses import FileResponse, StreamingResponse
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
# --- 自動升級資料庫欄位 (相容舊資料) ---
@app.on_event("startup")
def startup_event():
    session = db.SessionLocal()
    try:
        # 嘗試自動為現有的資料表補上 password 欄位
        session.execute(text("ALTER TABLE users ADD COLUMN password VARCHAR DEFAULT '0000'"))
        session.commit()
    except Exception:
        session.rollback() # 如果欄位已經存在就會報錯，我們直接忽略即可
    finally:
        session.close()

# --- 新增 API：取得所有已註冊學生名單 ---
@app.get("/users")
def get_all_users(dbs: Session = Depends(get_db)):
    users = dbs.query(db.User).all()
    return [{"id": u.id, "username": u.username} for u in users]

# --- 新增 API：註冊新帳號 ---
@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), dbs: Session = Depends(get_db)):
    # 檢查名字是否被用過
    if dbs.query(db.User).filter_by(username=username).first():
        return {"status": "error", "message": "這個名字已經有人註冊囉！"}
    
    # 驗證密碼：至少4個字，且必須是數字
    if not password.isdigit() or len(password) < 4:
        return {"status": "error", "message": "密碼必須至少為 4 個數字！"}
        
    new_user = db.User(username=username, password=password)
    dbs.add(new_user)
    dbs.commit()
    dbs.refresh(new_user)
    return {"status": "success", "user_id": new_user.id, "username": new_user.username}

# --- 修改 API：安全登入 ---
@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), dbs: Session = Depends(get_db)):
    user = dbs.query(db.User).filter_by(username=username).first()
    if not user:
        return {"status": "error", "message": "找不到此學生，請先切換到註冊畫面！"}
    
    # 核對密碼 (舊帳號密碼預設為 0000)
    if user.password and user.password != password:
        return {"status": "error", "message": "密碼錯誤！"}
        
    return {"status": "success", "user_id": user.id, "username": user.username}

@app.get("/users/{user_id}/sets")
def get_user_sets(user_id: int, dbs: Session = Depends(get_db)):
    return dbs.query(db.WordSet).filter_by(owner_id=user_id).all()

@app.get("/wrong_answers/{user_id}")
def get_wrong_answers(user_id: int, dbs: Session = Depends(get_db)):
    # 👑 錯題本也一併加入洗牌機制，才不會每次都從同一個字開始錯
    wrong_records = dbs.query(db.WrongAnswer).filter_by(user_id=user_id).order_by(func.random()).all()
    return [r.word for r in wrong_records]

@app.get("/quiz/{set_id}")
def get_quiz(set_id: int, dbs: Session = Depends(get_db)):
    # 👑 加上 .order_by(func.random())，讓資料庫直接把這 45 題徹底洗牌再回傳
    return dbs.query(db.Word).filter_by(word_set_id=set_id).order_by(func.random()).all()

@app.post("/submit_answer")
def submit_answer(user_id: int = Form(...), word_id: int = Form(...), is_correct: str = Form(...), dbs: Session = Depends(get_db)):
    # 👑 強制轉換前端傳來的字串，避免型別誤判
    is_true = is_correct.lower() in ['true', '1', 'yes']
    
    if not is_true:
        # ❌ 答錯：如果錯題本裡還沒有，就新增進去
        exists = dbs.query(db.WrongAnswer).filter_by(user_id=user_id, word_id=word_id).first()
        if not exists:
            dbs.add(db.WrongAnswer(user_id=user_id, word_id=word_id))
            dbs.commit()
    else:
        # ✅ 答對：確保把錯題本裡的紀錄清得乾乾淨淨
        wrong_records = dbs.query(db.WrongAnswer).filter_by(user_id=user_id, word_id=word_id).all()
        for r in wrong_records:
            dbs.delete(r)
        dbs.commit()
            
    return {"status": "recorded"}

async def fetch_example_sentence(word: str):
    examples = []
    try:
        # 設定 timeout=5.0，避免網路卡住導致整個伺服器當機
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
            if resp.status_code == 200:
                data = resp.json()
                raw_exs = []
                # 穿梭字典 API 的結構，找出例句 (最多找 2 句)
                for entry in data:
                    for m in entry.get("meanings", []):
                        for d in m.get("definitions", []):
                            if d.get("example"): 
                                raw_exs.append(d["example"])
                            if len(raw_exs) >= 2: break
                
                # 呼叫 Google 翻譯把英文例句翻成中文
                gt = GoogleTranslator(source='en', target='zh-TW')
                for ex in raw_exs:
                    examples.append({"en": ex, "zh": gt.translate(ex)})
    except Exception as e:
        print(f"抓取 {word} 的例句失敗: {e}")
        pass
        
    # 保底機制：如果真的找不到例句，或者網路斷線，就給預設句子
    if not examples: 
        examples = [{"en": f"I am learning the word {word}.", "zh": f"我正在學習 {word} 這個單字。"}]
        
    return json.dumps(examples)

# --- 下載 CSV 範例檔 ---
@app.get("/download_template")
def download_template():
    # 加入了 example_sentence 欄位，並示範了「有填例句」與「沒填例句」的寫法
    csv_content = (
        "\ufeffword,pos,chinese,example_sentence\n"
        "apple,n,蘋果,I eat an apple every day.\n"
        "run,v,跑步,She likes to run in the park.\n"
        "beautiful,adj,美麗的,\n"  # 示範留白：這格不填的話，系統會自動找 AI 抓例句
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=template.csv"}
    )

# --- 新增功能 2：手動新增單字到現有題組 ---
@app.post("/sets/{set_id}/words")
async def add_word_to_set(
    set_id: int, 
    english: str = Form(...), 
    part_of_speech: str = Form(""), 
    chinese: str = Form(...), 
    example_sentence: str = Form(""), 
    dbs: Session = Depends(get_db)
):
    # 檢查題組是否存在
    word_set = dbs.query(db.WordSet).filter(db.WordSet.id == set_id).first()
    if not word_set:
        return {"status": "error", "message": "找不到該題組"}

    english = english.strip()
    
    # 如果使用者沒有填寫例句，就呼叫 AI 自動產生
    if not example_sentence.strip():
        ex_json = await fetch_example_sentence(english)
    else:
        # 如果有自己填，就打包成 JSON 格式儲存
        ex_json = json.dumps([{"en": example_sentence.strip(), "zh": "（老師自訂例句）"}])

    new_word = db.Word(
        english=english,
        part_of_speech=part_of_speech.strip(),
        chinese=chinese.strip(),
        example_sentence=ex_json,
        word_set_id=set_id
    )
    dbs.add(new_word)
    dbs.commit()
    
    return {"status": "success"}


@app.post("/upload_csv/{user_id}")
async def upload_csv(user_id: int, set_name: str = Form(...), file: UploadFile = File(...)):
    content = (await file.read()).decode('utf-8-sig').splitlines()
    reader = csv.DictReader(content)

    # 防呆機制：標題轉小寫去空白
    if reader.fieldnames:
        reader.fieldnames = [str(f).strip().lower() if f else "" for f in reader.fieldnames]

    rows = [row for row in reader if str(row.get('word') or '').strip()]
    total = len(rows)

    async def generate():
        dbs = db.SessionLocal()
        try:
            new_set = db.WordSet(name=set_name, owner_id=user_id)
            dbs.add(new_set)
            dbs.commit()
            dbs.refresh(new_set)

            yield f"data: {json.dumps({'total': total, 'current': 0})}\n\n"

            for i, row in enumerate(rows):
                word = str(row.get('word') or '').strip()
                pos  = str(row.get('pos')  or '').strip()
                chinese = str(row.get('chinese') or '').strip()
                csv_example = str(row.get('example_sentence') or '').strip()

                if csv_example:
                    # CSV 有填例句，直接使用，不呼叫 API
                    ex_json = json.dumps([{"en": csv_example, "zh": "（自訂例句）"}])
                else:
                    # CSV 沒有例句，才去抓 API
                    ex_json = await fetch_example_sentence(word)

                dbs.add(db.Word(
                    english=word,
                    part_of_speech=pos,
                    chinese=chinese,
                    example_sentence=ex_json,
                    word_set_id=new_set.id
                ))
                dbs.commit()

                yield f"data: {json.dumps({'total': total, 'current': i + 1, 'word': word})}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            print(f"上傳發生錯誤: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            dbs.close()

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.delete("/sets/{set_id}")
def delete_set(set_id: int, dbs: Session = Depends(get_db)):
    # 1. 尋找指定的題組
    word_set = dbs.query(db.WordSet).filter(db.WordSet.id == set_id).first()
    if not word_set:
        return {"status": "error", "message": "找不到題組"}
    
    # 2. 安全機制：找出這個題組裡的所有單字，並先刪除與它們相關的「錯題紀錄」
    words = dbs.query(db.Word).filter(db.Word.word_set_id == set_id).all()
    word_ids = [w.id for w in words]
    if word_ids:
        # synchronize_session=False 可以讓大量刪除的效能更好
        dbs.query(db.WrongAnswer).filter(db.WrongAnswer.word_id.in_(word_ids)).delete(synchronize_session=False)
    
    # 3. 刪除題組 (因為我們在 database.py 有設定 cascade，裡面的單字也會跟著自動刪除)
    dbs.delete(word_set)
    dbs.commit()
    return {"status": "success"}


@app.get("/")
def read_index(): return FileResponse("static/index.html")