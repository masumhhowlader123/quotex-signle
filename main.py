import os
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image
import io
import json
from google import genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

client = genai.Client(api_key=GEMINI_API_KEY)

USERS_DB = {
    "admin": "731491",
}

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
    if data.username in USERS_DB and USERS_DB[data.username] == data.password:
        is_admin = (data.username == "admin")
        return JSONResponse(content={"success": True, "is_admin": is_admin, "message": "Login successful!"})
    else:
        raise HTTPException(status_code=401, detail="Invalid username or password!")

@app.post("/add-user")
async def add_user(data: NewUserRequest):
    if data.admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    if data.new_username in USERS_DB:
        raise HTTPException(status_code=400, detail="Username already exists!")
    
    USERS_DB[data.new_username] = data.new_password
    return JSONResponse(content={"success": True, "message": f"User '{data.new_username}' created successfully!"})

@app.get("/users-list")
async def get_users_list(admin_user: str):
    if admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    users = [{"username": u} for u in USERS_DB.keys() if u != "admin"]
    return JSONResponse(content={"users": users})

@app.post("/delete-user")
async def delete_user(data: DeleteUserRequest):
    if data.admin_user != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized action!")
    
    if data.username_to_delete == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin!")
    
    if data.username_to_delete in USERS_DB:
        del USERS_DB[data.username_to_delete]
        return JSONResponse(content={"success": True, "message": f"User '{data.username_to_delete}' deleted successfully!"})
    else:
        raise HTTPException(status_code=404, detail="User not found!")

@app.post("/analyze-screenshot")
async def analyze_screenshot(file: UploadFile = File(...), feedback: str = Form(None)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed.")
    
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        correction_prompt = ""
        if feedback:
            correction_prompt = f" SPECIAL USER FEEDBACK/CORRECTION FROM PREVIOUS MISTAKE: '{feedback}'. Please strictly follow this instruction and fix your strategy."

        prompt = (
            "Analyze this trading chart screenshot for binary options." + correction_prompt +
            " Return the response strictly as a valid JSON object with the following keys, and nothing else: "
            "{\"asset\": \"Asset Name\", "
            "\"action\": \"CALL (UP) or PUT (DOWN) or NO TRADE\", "
            "\"expiry\": \"1 Minute\", "
            "\"accuracy\": \"e.g. 92%\", "
            "\"support_resistance\": \"e.g. Support at 1.22200 / Resistance at 1.22300\", "
            "\"trend_strength\": \"e.g. 88%\", "
            "\"trade_decision\": \"TRADE (Low Risk) or NO TRADE (High Risk)\", "
            "\"banglish_logic\": \"Keno CALL ba PUT dilo, tar puro technical explanation sohoj Banglish a likhba.\"}"
        )

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[image, prompt]
        )

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
            "expiry": "1 Min",
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