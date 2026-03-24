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
    value = data['entry'][0]['changes'][0]['value']
    if 'messages' not in value:
        return "ok", 200  # Likely a status update, ignore
    message = value['messages'][0]
    sender_id = message['from']  # The user's phone number
    msg_type = message['type']
    # Extract content based on type
    text_body = message['text']['body'].strip() if msg_type == 'text' else None
    image_id = message['image']['id'] if msg_type == 'image' else None
    return ParsedMessage(
        text_body=text_body,
        image_id=image_id,
        sender_id=sender_id,
        msg_type=msg_type
    )


def send_message(to, body_text):
    """Helper to hit Facebook Graph API"""
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body_text}
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
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "id": image_id  # We use the ID, not a link!
        }
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send image: {e}")
