import os
import random
import json
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image
import io
from google import genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ক্রন জবের (cron-job.org) 404 এরর দূর করার জন্য রুট এন্ডপয়েন্ট
@app.get("/")
async def root():
    return {"status": "active", "message": "Quotex AI Signal API is running successfully!"}

# ইউজার ডাটা ফাইল পাথ
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    default_users = {"admin": "731491"}
    save_users(default_users)
    return default_users

def save_users(users_dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users_dict, f, indent=4)

USERS_DB = load_users()

def get_gemini_clients():
    keys = []
    main_key = os.environ.get("GEMINI_API_KEY", "")
    if main_key:
        keys.append(main_key)
    
    for i in range(1, 11):
        k = os.environ.get(f"GEMINI_API_KEY_{i}", "")
        if k and k not in keys:
            keys.append(k)
            
    return keys

API_KEYS = get_gemini_clients()

class LoginRequest(BaseModel):
    username: str
    password: str

class NewUserRequest(BaseModel):
    admin_user: str
    new_username: str
    new_password: str

class DeleteUserRequest(BaseModel):
    admin_user: str
    username_to_delete: str

@app.post("/login")
async def login(data: LoginRequest):
    global USERS_DB
    USERS_DB = load_users()
    if data.username in USERS_DB and USERS_DB[data.username] == data.password:
        is_admin = (data.username == "admin")
        return JSONResponse(content={"success": True, "is_admin": is_admin, "message": "Login successful!"})
    else:
        raise HTTPException(status_code=401, detail="Invalid username or password!")

@app.post("/add-user")
async def add_user(data: NewUserRequest):
    global USERS_DB
    USERS_DB = load_users()
    
    if data.admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    if data.new_username in USERS_DB:
        raise HTTPException(status_code=400, detail="Username already exists!")
    
    USERS_DB[data.new_username] = data.new_password
    save_users(USERS_DB)
    return JSONResponse(content={"success": True, "message": f"User '{data.new_username}' created successfully!"})

@app.get("/users-list")
async def get_users_list(admin_user: str):
    global USERS_DB
    USERS_DB = load_users()
    
    if admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    users = [{"username": u} for u in USERS_DB.keys() if u != "admin"]
    return JSONResponse(content={"users": users})

@app.post("/delete-user")
async def delete_user(data: DeleteUserRequest):
    global USERS_DB
    USERS_DB = load_users()
    
    if data.admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    if data.username_to_delete == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin!")
    
    if data.username_to_delete in USERS_DB:
        del USERS_DB[data.username_to_delete]
        save_users(USERS_DB)
        return JSONResponse(content={"success": True, "message": f"User '{data.username_to_delete}' deleted successfully!"})
    else:
        raise HTTPException(status_code=404, detail="User not found!")

@app.post("/analyze-screenshot")
async def analyze_screenshot(file: UploadFile = File(...), feedback: str = Form(None)):
    global API_KEYS
    API_KEYS = get_gemini_clients()
    
    if not API_KEYS:
        return JSONResponse(content={
            "asset": "Unknown", "action": "NO TRADE", "expiry": "2 Minutes", "accuracy": "0%",
            "support_resistance": "N/A", "trend_strength": "0%", "trade_decision": "NO TRADE (High Risk)",
            "banglish_logic": "Analysis error: No Gemini API keys found in environment variables."
        })

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed.")
    
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        # স্পিড বাড়ানোর জন্য ছবি রিসাইজ করা (512x512)
        image.thumbnail((512, 512))

        correction_prompt = ""
        if feedback:
            correction_prompt = f" FEEDBACK: '{feedback}'."

        # কঠোরভাবে ২ মিনিটের সিগন্যাল দেওয়ার জন্য অপ্টিমাইজড প্রম্পট
        prompt = (
            "Analyze trading chart instantly for a strict 2 MINUTES expiry trade." + correction_prompt +
            " Return ONLY a raw JSON object with these keys: "
            "{\"asset\": \"Asset Name\", "
            "\"action\": \"CALL (UP) or PUT (DOWN) or NO TRADE\", "
            "\"expiry\": \"2 Minutes\", "
            "\"accuracy\": \"e.g. 92%\", "
            "\"support_resistance\": \"Levels\", "
            "\"trend_strength\": \"Strength\", "
            "\"trade_decision\": \"TRADE (Low Risk) or NO TRADE (High Risk)\", "
            "\"banglish_logic\": \"2 minutes expiry er jonno choto kore reason Banglish a likhba.\"}"
        )

        shuffled_keys = list(API_KEYS)
        random.shuffle(shuffled_keys)
        
        response = None
        last_exception = None

        for key in shuffled_keys:
            try:
                temp_client = genai.Client(api_key=key)
                response = temp_client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[image, prompt]
                )
                break
            except Exception as ex:
                last_exception = ex
                continue

        if response is None:
            raise last_exception if last_exception else Exception("All API keys failed.")

        raw_text = response.text.strip()
        
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        signal_data = json.loads(raw_text)
        return JSONResponse(content=signal_data)

    except Exception as e:
        return JSONResponse(content={
            "asset": "Unknown",
            "action": "NO TRADE",
            "expiry": "2 Minutes",
            "accuracy": "0%",
            "support_resistance": "N/A",
            "trend_strength": "0%",
            "trade_decision": "NO TRADE (High Risk)",
            "banglish_logic": "Analysis error: " + str(e)
        })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)