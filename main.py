from fastapi import FastAPI, Request
import httpx
import google.generativeai as genai
import os
import json
from datetime import datetime

app = FastAPI()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mysecrettoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# =============================================
# CONVERSATION HISTORY (In-memory storage)
# =============================================
conversation_history = {}
booking_data = {}

# =============================================
# EGLAI TOURS - COMPLETE SYSTEM PROMPT
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

### 🏔️ NORTHERN PAKISTAN TOURS:
1. **Hunza Valley Tour** (5 Days / 4 Nights)
   - Price: PKR 45,000/person
   - Includes: Transport, Hotel, Breakfast & Dinner, Guide
   - Highlights: Attabad Lake, Baltit Fort, Passu Cones, Eagle's Nest
   
2. **Skardu Adventure Tour** (6 Days / 5 Nights)
   - Price: PKR 55,000/person
   - Includes: Transport, Hotel, All Meals, Guide, Jeep Safari
   - Highlights: Shangrila Resort, Deosai Plains, Satpara Lake, Shigar Fort
   
3. **Swat Valley Tour** (4 Days / 3 Nights)
   - Price: PKR 30,000/person
   - Includes: Transport, Hotel, Breakfast, Guide
   - Highlights: Malam Jabba, Mahodand Lake, Kalam, Mingora

4. **Hunza + Skardu Combined** (9 Days / 8 Nights)
   - Price: PKR 90,000/person
   - Includes: Everything above combined
   
### 🌲 CENTRAL PAKISTAN TOURS:
5. **Murree & Nathiagali Tour** (3 Days / 2 Nights)
   - Price: PKR 18,000/person
   - Includes: Transport, Hotel, Breakfast
   - Highlights: Mall Road, Patriata, Nathiagali Forest
   
6. **Azad Kashmir Tour** (4 Days / 3 Nights)
   - Price: PKR 28,000/person
   - Includes: Transport, Hotel, Breakfast & Dinner, Guide
   - Highlights: Neelum Valley, Ratti Gali Lake, Sharda

### 🏛️ HISTORICAL TOURS:
7. **Lahore Heritage Tour** (2 Days / 1 Night)
   - Price: PKR 12,000/person
   - Includes: Transport, Hotel, Breakfast, Guide
   - Highlights: Badshahi Mosque, Lahore Fort, Shalimar Gardens, Food Street
   
8. **Multan & Mohenjo-daro Tour** (3 Days / 2 Nights)
   - Price: PKR 22,000/person

### 🎯 CUSTOM TOURS:
- Any destination customized as per customer requirement
- Price: Depends on requirements

## BOOKING PROCESS:
When customer wants to book, collect this info ONE BY ONE (not all at once):
1. Full Name
2. Phone Number (if not already known)
3. City (from where they will travel)
4. Tour Name / Destination
5. Number of Persons
6. Preferred Travel Date
7. Any special requirements (honeymoon, family, adventure, etc.)

After collecting all info, show a BOOKING SUMMARY and ask for confirmation.

## DISCOUNTS:
- Group of 5+: 10% discount
- Group of 10+: 15% discount
- Early booking (30 days+): 5% discount
- Honeymoon package: Special romantic additions free

## CONTACT INFO:
- WhatsApp/Phone: Available 24/7 via this chatbot
- Email: info@eglai.store
- Website: https://eglai.store
- Cities: Lahore, Karachi, Islamabad, Multan, Faisalabad

## LANGUAGE RULES:
- If customer writes in Urdu/Roman Urdu → Reply in Roman Urdu (easy to read)
- If customer writes in English → Reply in English
- Always be friendly, helpful and professional
- Use emojis to make conversation engaging 😊
- Never be rude or dismissive

## IMPORTANT RULES:
- Always greet new customers warmly
- Be patient and answer all questions
- If you don't know something specific, say you'll check and get back
- Always try to convert inquiries into bookings
- After booking confirmation, give a booking reference number (EGLAI + random 4 digits)
- Remind customers that 30% advance payment is required to confirm booking
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

            # Only handle text messages
            if msg_type == "text":
                user_text = msg.get("text", {}).get("body", "")

                if user_text:
                    # Get AI response
                    reply = await get_ai_response(sender_id, user_text)
                    # Send reply
                    await send_whatsapp(sender_id, reply)

    except Exception as e:
        print(f"Error: {e}")

    return {"status": "ok"}

# =============================================
# AI RESPONSE WITH CONVERSATION HISTORY
# =============================================
async def get_ai_response(sender_id: str, user_message: str) -> str:
    try:
        # Initialize conversation history for new users
        if sender_id not in conversation_history:
            conversation_history[sender_id] = []
            # Welcome new user
            welcome_context = "This is a NEW customer. Greet them warmly and introduce Eglai Tours briefly."
            user_message_with_context = f"{welcome_context}\n\nCustomer message: {user_message}"
        else:
            user_message_with_context = user_message

        # Add user message to history
        conversation_history[sender_id].append({
            "role": "user",
            "parts": [user_message_with_context]
        })

        # Keep only last 20 messages to avoid token limit
        if len(conversation_history[sender_id]) > 20:
            conversation_history[sender_id] = conversation_history[sender_id][-20:]

        # Create chat with history
        chat = model.start_chat(history=conversation_history[sender_id][:-1])

        # Get response
        response = chat.send_message(
            EGLAI_SYSTEM_PROMPT + "\n\n" + user_message_with_context
        )

        reply = response.text

        # Add assistant response to history
        conversation_history[sender_id].append({
            "role": "model",
            "parts": [reply]
        })

        return reply

    except Exception as e:
        print(f"AI Error: {e}")
        return "Assalam o Alaikum! 🌟 Eglai Tours mein khush amdeed! Abhi hamara system thora busy hai, please thori der baad dobara try karein. Shukriya! 🙏"

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

        # Split long messages (WhatsApp limit is 4096 chars)
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
        "status": "✅ Eglai Tours Chatbot is Running!",
        "company": "Eglai Tours Pakistan",
        "timestamp": datetime.now().isoformat()
    }
