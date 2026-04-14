from fastapi import FastAPI, Request
import httpx
import google.generativeai as genai
import os

app = FastAPI()

# API Keys - Environment Variables se lenge
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mysecrettoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Webhook Verify
@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params["hub.challenge"])
    return {"error": "Invalid token"}

# Messages Receive
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
            user_text = msg.get("text", {}).get("body", "")
            sender_id = msg.get("from", "")

            if user_text:
                response = model.generate_content(
                    f"Aap ek helpful company assistant hain. Seedha aur mukhtasar jawab do. User ne kaha: {user_text}"
                )
                reply = response.text
                await send_whatsapp(sender_id, reply)
    except Exception as e:
        print(f"Error: {e}")

    return {"status": "ok"}

# WhatsApp Message Send
async def send_whatsapp(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)
