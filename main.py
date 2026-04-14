from fastapi import FastAPI, Request
import httpx
import google.generativeai as genai
import os
import asyncio
from datetime import datetime

app = FastAPI()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mysecrettoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

# Gemini Setup - 2.0 Flash (faster + more free quota)
genai.configure(api_key=GEMINI_API_KEY)

# Conversation History
conversation_history = {}
known_users = set()
last_message_time = {}

# =============================================
# EGLAI TOURS - SYSTEM PROMPT
# =============================================
EGLAI_SYSTEM_PROMPT = """
You are a friendly AI travel agent for Eglai Tours — a premium travel company in Pakistan.

PERSONALITY: Friendly, helpful, professional. Talk like a real travel agent friend.
Use Roman Urdu if customer writes in Urdu, English if they write in English.
Use emojis naturally. Never be robotic.

TOURS & PRICES:
1. Hunza Valley - 5 din/4 raatein - PKR 45,000/person
   (Attabad Lake, Baltit Fort, Passu Cones, Eagle's Nest)

2. Skardu Adventure - 6 din/5 raatein - PKR 55,000/person
   (Shangrila Resort, Deosai Plains, Satpara Lake, Shigar Fort)

3. Swat Valley - 4 din/3 raatein - PKR 30,000/person
   (Malam Jabba, Mahodand Lake, Kalam, Mingora)

4. Hunza + Skardu Combined - 9 din/8 raatein - PKR 90,000/person

5. Murree & Nathiagali - 3 din/2 raatein - PKR 18,000/person
   (Mall Road, Patriata, Nathiagali Forest)

6. Azad Kashmir - 4 din/3 raatein - PKR 28,000/person
   (Neelum Valley, Ratti Gali Lake, Sharda)

7. Lahore Heritage - 2 din/1 raat - PKR 12,000/person
   (Badshahi Mosque, Lahore Fort, Shalimar Gardens, Food Street)

8. Custom Tour - Price depends on requirements

DISCOUNTS:
- 5+ log: 10% off
- 10+ log: 15% off
- 30 din pehle booking: 5% off
- Honeymoon package: Free romantic extras

BOOKING - collect ONE BY ONE:
1. Poora naam
2. Phone number
3. Departure city
4. Tour name
5. Kitne log
6. Travel date
7. Special requirements
Then show summary, confirm, give ref: EGLAI + 4 digits
30% advance payment zaroori hai.

CONTACT:
- Email: info@eglai.store
- Website: https://eglai.store
- Available: 24/7

RULES:
- Har message ka jawab do chahe "Hi" ho ya "Hello" ya "kya hal h"
- KABHI same reply repeat mat karo
- Conversation yaad rakho aur uske mutabiq jawab do
- Pehli baar milna ho toh warmly greet karo aur tours introduce karo
- Dusri baar se directly unke sawaal ka jawab do
- Booking process mein ek ek cheez poochho
- Agar koi simple greeting kare toh friendly reply do aur poochho kaise help kar sakte hain
"""

# =============================================
# WEBHOOK VERIFY
# =============================================
@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params["hub.challenge"])
    return {"error": "Invalid token"}

# =============================================
# RECEIVE MESSAGES
# =============================================
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        entry = data["entry"][0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            msg_type = msg.get("type", "")
            sender_id = msg.get("from", "")

            if msg_type == "text":
                user_text = msg.get("text", {}).get("body", "")
                if user_text:
                    # Rate limit - 2 second gap
                    now = datetime.now().timestamp()
                    last_time = last_message_time.get(sender_id, 0)
                    if now - last_time < 2:
                        await asyncio.sleep(2 - (now - last_time))
                    last_message_time[sender_id] = datetime.now().timestamp()

                    reply = await get_ai_response(sender_id, user_text)
                    await send_whatsapp(sender_id, reply)

    except Exception as e:
        print(f"Webhook Error: {e}")

    return {"status": "ok"}

# =============================================
# AI RESPONSE WITH gemini-2.0-flash
# =============================================
async def get_ai_response(sender_id: str, user_message: str) -> str:
    is_new_user = sender_id not in known_users
    try:
        if sender_id not in conversation_history:
            conversation_history[sender_id] = []

        if is_new_user:
            known_users.add(sender_id)

        # Build conversation history text
        history_text = ""
        for msg in conversation_history[sender_id][-10:]:
            role = "Customer" if msg["role"] == "user" else "Agent"
            history_text += f"{role}: {msg['parts'][0]}\n"

        if is_new_user:
            full_prompt = f"""{EGLAI_SYSTEM_PROMPT}

---
CONVERSATION:
(Yeh customer pehli baar aa raha hai)
Customer: {user_message}
Agent:"""
        else:
            full_prompt = f"""{EGLAI_SYSTEM_PROMPT}

---
CONVERSATION HISTORY:
{history_text}
Customer: {user_message}
Agent:"""

        # Retry 3 times
        for attempt in range(3):
            try:
                # Using gemini-2.0-flash for better free quota
                model = genai.GenerativeModel("gemini-2.0-flash")
                response = model.generate_content(full_prompt)
                reply = response.text.strip()

                # Save to history
                conversation_history[sender_id].append({
                    "role": "user",
                    "parts": [user_message]
                })
                conversation_history[sender_id].append({
                    "role": "model",
                    "parts": [reply]
                })

                # Keep last 20 messages only
                if len(conversation_history[sender_id]) > 20:
                    conversation_history[sender_id] = conversation_history[sender_id][-20:]

                return reply

            except Exception as e:
                print(f"Gemini attempt {attempt+1} error: {e}")
                if "429" in str(e) or "quota" in str(e).lower():
                    await asyncio.sleep(5)
                elif attempt < 2:
                    await asyncio.sleep(2)
                else:
                    raise e

    except Exception as e:
        print(f"AI Error: {e}")
        if is_new_user:
            return "Assalam o Alaikum! 🌟 Eglai Tours mein khush amdeed! Main aapka travel assistant hun. Hunza, Skardu, Swat, Murree — Pakistan ke behtareen tours hain hamare paas! Kaunsa tour pasand hai aapko? 😊"
        else:
            return "Ji! Bataiye main kaise help kar sakta hun? 😊"

# =============================================
# SEND WHATSAPP MESSAGE
# =============================================
async def send_whatsapp(to: str, message: str):
    try:
        url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "text": {"body": chunk}
                }
                async with httpx.AsyncClient() as client:
                    await client.post(url, json=payload, headers=headers)
                await asyncio.sleep(0.5)
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "text": {"body": message}
            }
            async with httpx.AsyncClient() as client:
                await client.post(url, json=payload, headers=headers)

    except Exception as e:
        print(f"WhatsApp Send Error: {e}")

# =============================================
# HEALTH CHECK
# =============================================
@app.get("/")
async def health_check():
    return {
        "status": "Eglai Tours Chatbot Running!",
        "model": "gemini-2.0-flash",
        "timestamp": datetime.now().isoformat()
    }
