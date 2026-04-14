from fastapi import FastAPI, Request
import httpx
import google.generativeai as genai
import os
import asyncio
from datetime import datetime
import json

app = FastAPI()

# ENV
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mysecrettoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

genai.configure(api_key=GEMINI_API_KEY)

# Memory (optimized)
conversation_history = {}
user_state = {}
last_message_time = {}

# =========================
# SAVE LEADS (FILE BASED)
# =========================
def save_lead(data):
    try:
        with open("leads.json", "a") as f:
            f.write(json.dumps(data) + "\n")
    except:
        pass

# =========================
# VERIFY WEBHOOK
# =========================
@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params["hub.challenge"])
    return {"error": "Invalid token"}

# =========================
# RECEIVE MESSAGE
# =========================
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = msg["from"]
        text = msg.get("text", {}).get("body", "")

        # Rate limit
        now = datetime.now().timestamp()
        if now - last_message_time.get(sender, 0) < 1:
            await asyncio.sleep(1)
        last_message_time[sender] = now

        reply = await handle_message(sender, text)
        await send_whatsapp(sender, reply)

    except Exception as e:
        print("Error:", e)

    return {"ok": True}

# =========================
# HANDLE MESSAGE
# =========================
async def handle_message(sender, text):

    # BOOKING FLOW
    if sender in user_state:
        state = user_state[sender]

        if state["step"] == "name":
            state["name"] = text
            state["step"] = "city"
            return "Great 👍 Ap kis city se travel karenge?"

        elif state["step"] == "city":
            state["city"] = text
            state["step"] = "people"
            return "Kitne log travel karenge?"

        elif state["step"] == "people":
            state["people"] = text
            state["step"] = "date"
            return "Travel date kya hai?"

        elif state["step"] == "date":
            state["date"] = text

            # SAVE LEAD
            save_lead(state)

            user_state.pop(sender)

            return f"""✅ Booking request received!

Name: {state['name']}
City: {state['city']}
People: {state['people']}
Date: {state['date']}

Hamari team jaldi contact karegi 😊"""

    # TRIGGER BOOKING
    if "book" in text.lower():
        user_state[sender] = {"step": "name"}
        return "Great 😊 Booking start karte hain!\nApna poora naam batayein?"

    # AI RESPONSE
    return await get_ai_response(sender, text)

# =========================
# AI RESPONSE
# =========================
async def get_ai_response(sender, user_message):

    if sender not in conversation_history:
        conversation_history[sender] = []

    # last 5 messages only
    history = conversation_history[sender][-5:]

    history_text = ""
    for msg in history:
        role = "User" if msg["role"] == "user" else "Agent"
        history_text += f"{role}: {msg['text']}\n"

    prompt = f"""
You are a friendly travel agent for Eglai Tours in Pakistan.
Be natural, use Urdu/English mix, friendly tone.

Tours:
Hunza 45k, Skardu 55k, Swat 30k, Murree 18k

Conversation:
{history_text}
User: {user_message}
Agent:
"""

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        reply = response.text.strip()

        # Save memory (limit)
        conversation_history[sender].append({"role": "user", "text": user_message})
        conversation_history[sender].append({"role": "bot", "text": reply})

        if len(conversation_history[sender]) > 10:
            conversation_history[sender] = conversation_history[sender][-10:]

        return reply

    except:
        return "Sorry 😔 thori issue aa rahi hai. Dobara try karein."

# =========================
# SEND WHATSAPP
# =========================
async def send_whatsapp(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)

# =========================
# HEALTH
# =========================
@app.get("/")
async def home():
    return {"status": "Bot Running 🚀"}
