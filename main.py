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

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)

# Conversation History - per user
conversation_history = {}
# Track if user is new or existing
known_users = set()

# =============================================
# EGLAI TOURS - SYSTEM PROMPT
# =============================================
EGLAI_SYSTEM_PROMPT = """
You are an AI assistant for **Eglai Tours** — a premium travel company operating across Pakistan.

## YOUR ROLE:
You help customers with:
1. Tour information & packages
2. Booking tours (collect all details step by step)
3. Pricing & availability
4. Travel tips & advice
5. Answering any travel-related questions about Pakistan

## EGLAI TOURS - PACKAGES & PRICING:

### NORTHERN PAKISTAN TOURS:
1. Hunza Valley Tour (5 Days / 4 Nights)
   - Price: PKR 45,000/person
   - Includes: Transport, Hotel, Breakfast & Dinner, Guide
   - Highlights: Attabad Lake, Baltit Fort, Passu Cones, Eagle's Nest

2. Skardu Adventure Tour (6 Days / 5 Nights)
   - Price: PKR 55,000/person
   - Includes: Transport, Hotel, All Meals, Guide, Jeep Safari
   - Highlights: Shangrila Resort, Deosai Plains, Satpara Lake, Shigar Fort

3. Swat Valley Tour (4 Days / 3 Nights)
   - Price: PKR 30,000/person
   - Includes: Transport, Hotel, Breakfast, Guide
   - Highlights: Malam Jabba, Mahodand Lake, Kalam, Mingora

4. Hunza + Skardu Combined (9 Days / 8 Nights)
   - Price: PKR 90,000/person

### CENTRAL PAKISTAN TOURS:
5. Murree & Nathiagali Tour (3 Days / 2 Nights)
   - Price: PKR 18,000/person
   - Highlights: Mall Road, Patriata, Nathiagali Forest

6. Azad Kashmir Tour (4 Days / 3 Nights)
   - Price: PKR 28,000/person
   - Highlights: Neelum Valley, Ratti Gali Lake, Sharda

### HISTORICAL TOURS:
7. Lahore Heritage Tour (2 Days / 1 Night)
   - Price: PKR 12,000/person
   - Highlights: Badshahi Mosque, Lahore Fort, Shalimar Gardens

8. Multan Tour (3 Days / 2 Nights)
   - Price: PKR 22,000/person

### CUSTOM TOURS:
- Any destination as per customer requirement
- Price: Depends on requirements

## BOOKING PROCESS:
When customer wants to book, collect ONE BY ONE:
1. Full Name
2. Phone Number
3. City of departure
4. Tour Name
5. Number of Persons
6. Travel Date
7. Special requirements

Show BOOKING SUMMARY then confirm.
Give booking ref: EGLAI + 4 random digits
Remind: 30% advance required.

## DISCOUNTS:
- 5+ persons: 10% off
- 10+ persons: 15% off
- 30 days early booking: 5% off

## CONTACT:
- Email: info@eglai.store
- Website: https://eglai.store

## CRITICAL LANGUAGE & BEHAVIOR RULES:
1. Read the customer's EXACT message carefully
2. Reply DIRECTLY to what they asked — do NOT repeat welcome message
3. If they ask about Hunza -> give Hunza details
4. If they ask "kya kya krty ho" -> list all services/tours
5. If they want to book -> start booking process
6. Roman Urdu message -> reply in Roman Urdu
7. English message -> reply in English
8. NEVER give the same welcome message twice
9. Remember the FULL conversation and reply accordingly
10. Be natural, friendly, helpful like a real travel agent
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
                    reply = await get_ai_response(sender_id, user_text)
                    await send_whatsapp(sender_id, reply)

    except Exception as e:
        print(f"Webhook Error: {e}")

    return {"status": "ok"}

# =============================================
# AI RESPONSE - FIXED CONVERSATION TRACKING
# =============================================
async def get_ai_response(sender_id: str, user_message: str) -> str:
    try:
        # Initialize for new user
        is_new_user = sender_id not in known_users
        if sender_id not in conversation_history:
            conversation_history[sender_id] = []

        # Build messages list for Gemini
        messages = conversation_history[sender_id].copy()

        # Add current user message
        if is_new_user:
            # First time - add context that this is new customer
            full_message = f"[NEW CUSTOMER - greet warmly and introduce Eglai Tours]\nCustomer: {user_message}"
            known_users.add(sender_id)
        else:
            full_message = user_message

        messages.append({
            "role": "user",
            "parts": [full_message]
        })

        # Keep last 15 exchanges
        if len(messages) > 30:
            messages = messages[-30:]

        # Retry logic
        for attempt in range(3):
            try:
                model_instance = genai.GenerativeModel(
                    "gemini-1.5-flash",
                    system_instruction=EGLAI_SYSTEM_PROMPT
                )
                chat = model_instance.start_chat(history=messages[:-1])
                response = chat.send_message(full_message if is_new_user else user_message)
                reply = response.text

                # Save to history
                conversation_history[sender_id].append({
                    "role": "user",
                    "parts": [user_message]  # Save original message
                })
                conversation_history[sender_id].append({
                    "role": "model",
                    "parts": [reply]
                })

                # Keep history manageable
                if len(conversation_history[sender_id]) > 30:
                    conversation_history[sender_id] = conversation_history[sender_id][-30:]

                return reply

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    raise e

    except Exception as e:
        print(f"AI Error: {e}")
        return "Assalam o Alaikum! 🌟 Eglai Tours mein khush amdeed! Aap kaunsa tour dekhna chahte hain? Hunza, Skardu, Swat, Murree — sab available hain! 😊"

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
        "timestamp": datetime.now().isoformat()
    }
