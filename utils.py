import os

import requests
from dotenv import load_dotenv

from dataclasses import dataclass

load_dotenv()

WHATSAPP_TOKEN = os.getenv("TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")


@dataclass
class ParsedMessage:
    text_body: str
    image_id: str
    sender_id: str
    msg_type: str


def parse_message(data):
    # Extract basic message info
    print(data)
    value = data["entry"][0]["changes"][0]["value"]
    if "messages" not in value:
        return "ok", 200  # Likely a status update, ignore
    message = value["messages"][0]
    sender_id = message["from"]  # The user's phone number
    msg_type = message["type"]
    # Extract content based on type
    text_body = message["text"]["body"].strip() if msg_type == "text" else None
    image_id = message["image"]["id"] if msg_type == "image" else None
    return ParsedMessage(
        text_body=text_body, image_id=image_id, sender_id=sender_id, msg_type=msg_type
    )


def send_message(to, body_text):
    """Helper to hit Facebook Graph API"""
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body_text},
    }
    requests.post(url, headers=headers, json=payload)


def send_image(to, image_id):
    """
    Sends an image to a user using an existing Media ID.
    This effectively 'forwards' the image the user sent you.
    """
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": image_id},  # We use the ID, not a link!
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send image: {e}")


def send_template_message(to_number, template_name, name_var, link_var):
    """
    Sends an approved Meta Template message, bypassing the 24-hour window.
    """
    token = os.getenv("TOKEN")  # Your permanent Meta API token
    phone_number_id = os.getenv("PHONE_NUMBER_ID")  # Your WhatsApp Bot phone ID

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": "en"  # Must match your Meta template language exactly
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": name_var},  # Fills in {{1}}
                        {"type": "text", "text": link_var},  # Fills in {{2}}
                    ],
                }
            ],
        },
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code not in [200, 201]:
        print(f"❌ Template Failed: {response.text}")
    else:
        print(f"✅ Template sent to {to_number}")

    return response
