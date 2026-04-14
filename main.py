from fastapi import FastAPI, Request
import httpx
import google.generativeai as genai
import os

app = FastAPI()

# ====== CONFIG ======
VERIFY_TOKEN = "12345"
WHATSAPP_TOKEN = "PASTE_YOUR_TOKEN"
PHONE_NUMBER_ID = "PASTE_YOUR_ID"
GEMINI_API_KEY = "PASTE_YOUR_GEMINI_KEY"

genai.configure(api_key=GEMINI_API_KEY)

# ====== VERIFY ======
@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params["hub.challenge"])
    return {"error": "Invalid"}

# ====== WEBHOOK ======
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages", [])
        if not messages:
            return {"ok": True}

        msg = messages[0]
        sender = msg["from"]
        text = msg.get("text", {}).get("body", "")

        # SIMPLE LOGIC
        if "price" in text.lower():
            reply = "Hunza tour 45,000 PKR 😊\nSkardu 55,000 PKR"
        elif "book" in text.lower():
            reply = "Great 😊 Apna naam batayein booking ke liye"
        else:
            reply = await ai_reply(text)

        await send_message(sender, reply)

    except Exception as e:
        print(e)

    return {"ok": True}

# ====== AI ======
async def ai_reply(text):
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            f"You are travel agent. Reply friendly: {text}"
        )
        return response.text
    except:
        return "Server busy 😔"

# ====== SEND ======
async def send_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=data, headers=headers)

# ====== HOME ======
@app.get("/")
async def home():
    return {"status": "Bot Running 🚀"}
