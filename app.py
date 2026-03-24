import os
import hmac
import redis
import hashlib
import random
import string

from dotenv import load_dotenv
from flask import Flask, request, abort

from utils import parse_message, send_message, ParsedMessage, send_image

# ADDED NEW IMPORTS HERE
from db_manager import (
    log_request,
    log_proposal,
    close_request_in_db,
    save_artisan_application,
    approve_artisan_in_db,
    get_artisan_profile,
    complete_request_in_db,
)

load_dotenv()

token = os.getenv("VERIFY_TOKEN")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PASS = os.getenv("REDIS_PASS")
ADMIN_NO = os.getenv("ADMIN_NO")
ARTISAN_GROUP_INVITE_LINK = os.getenv(
    "WHATSAPP_GROUP_LINK", "https://chat.whatsapp.com/NO_INVITE_FOUND"
)

app = Flask(__name__)
r = redis.Redis(
    host=REDIS_HOST, password=REDIS_PASS, port=6379, db=10, decode_responses=True
)

# --- STATE CONSTANTS ---
STATE_START = "START"
STATE_WAITING_CATEGORY = "WAITING_CATEGORY"
STATE_WAITING_DESCRIPTION = "WAITING_DESCRIPTION"
STATE_WAITING_PHOTO = "WAITING_PHOTO"
STATE_WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
STATE_ARTISAN_PROPOSING = "ARTISAN_PROPOSING"
STATE_ONB_LOCATION = "ONB_LOCATION"
STATE_ONB_SKILL = "ONB_SKILL"
STATE_ONB_EXP = "ONB_EXP"
STATE_ONB_VIDEO = "ONB_VIDEO"

CATEGORIES = {
    "1": "Plumber",
    "2": "Electrician",
    "3": "Carpenter",
    "4": "AC/Fridge Repair",
    "5": "Phone/Laptop Repair",
    "6": "Other",
}


def generate_signature(secret_key, raw_payload):
    key_bytes = secret_key.encode("utf-8")
    payload_bytes = raw_payload
    signature = hmac.new(key_bytes, payload_bytes, hashlib.sha256)
    return signature.hexdigest()


def generate_ref_id():
    chars = string.ascii_uppercase + string.digits
    return "HND-" + "".join(random.choices(chars, k=5))


def generate_pin():
    return str(random.randint(1000, 9999))


@app.get("/")
def parse_data():
    mode = request.args.get("hub.mode")
    verify_token = request.args.get("hub.verify_token")
    if mode == "subscribe" and verify_token == token:
        return request.args.get("hub.challenge"), 200
    return "", 403


@app.post("/")
def payload():
    APP_SECRET = os.getenv("APP_SECRET")
    incoming_signature = request.headers.get("X-Hub-Signature-256")

    if incoming_signature is None:
        abort(403)

    prefix, signature_hash = incoming_signature.split("=")
    expected_hash = hmac.new(
        key=APP_SECRET.encode("utf-8"), msg=request.data, digestmod=hashlib.sha256
    ).hexdigest()

    if hmac.compare_digest(expected_hash, signature_hash):
        payload_data = request.get_json(force=True)
        try:
            parsed = parse_message(payload_data)
            if isinstance(parsed, ParsedMessage):
                sender_id = parsed.sender_id
                text_body = parsed.text_body or ""
                image_id = parsed.image_id
                msg_type = parsed.msg_type

                try:
                    video_id = (
                        payload_data["entry"][0]["changes"][0]["value"]["messages"][0][
                            "video"
                        ]["id"]
                        if msg_type == "video"
                        else None
                    )
                except KeyError:
                    video_id = None
            else:
                return "ok", 200
        except (KeyError, IndexError):
            return "ignored", 200

        state_key = f"handees:{sender_id}:state"
        current_state = r.get(state_key) or STATE_START

        data_key_cat = f"handees:{sender_id}:category"
        data_key_desc = f"handees:{sender_id}:desc"
        data_key_photo = f"handees:{sender_id}:photo"

        response_text = ""
        text_body_upper = text_body.strip().upper() if text_body else ""

        # ==========================================
        # 👑 ADMIN COMMAND: "APPRV <phone>"
        # ==========================================
        if (
            sender_id == ADMIN_NO
            and msg_type == "text"
            and text_body_upper.startswith("APPRV")
        ):
            parts = text_body_upper.split()
            if len(parts) >= 2:
                target_artisan = parts[1]
                approve_artisan_in_db(target_artisan)
                group_link = ARTISAN_GROUP_INVITE_LINK
                invite_msg = (
                    f"🎉 *Congratulations!* Your Handees application has been approved.\n\n"
                    f"Please join the official Handees Artisan network using this link to start receiving jobs:\n{group_link}\n\n"
                    f"Welcome to the team! 🛠️"
                )
                send_message(target_artisan, invite_msg)
                response_text = (
                    f"✅ Approved! Invite link successfully sent to {target_artisan}."
                )
            else:
                response_text = "⚠️ Invalid format. Use: APPRV <phone_number>"

            send_message(sender_id, response_text)
            return "", 200

        # ==========================================
        # 🤝 ARTISAN HANDSHAKE COMMAND: "DONE <REF> <PIN>"
        # ==========================================
        if msg_type == "text" and text_body_upper.startswith("DONE"):
            parts = text_body_upper.split()
            if len(parts) == 3:
                _, target_req, submitted_pin = parts
                actual_pin = r.get(f"req:{target_req}:pin")

                if actual_pin and actual_pin == submitted_pin:
                    # Mark complete in DB
                    complete_request_in_db(target_req, sender_id)

                    response_text = "🎉 *Job Completed!* You have successfully verified the handshake. Thank you for your great work!"

                    # Notify the customer that the system registered it
                    cust_id = r.get(f"req:{target_req}:customer")
                    if cust_id:
                        cust_msg = f"✅ Your Handees request *{target_req}* has been officially marked as completed by the artisan. Thank you for using Handees!"
                        send_message(cust_id, cust_msg)
                else:
                    response_text = "❌ Invalid PIN or Reference ID. Please check with the customer and try again."
            else:
                response_text = (
                    "⚠️ Format: DONE <REF_ID> <PIN>\n_Example: DONE HND-1A2B 5432_"
                )

            send_message(sender_id, response_text)
            return "", 200

        # ==========================================
        # 🛑 CUSTOMER "CLOSE" COMMAND
        # ==========================================
        if msg_type == "text" and (
            text_body_upper.strip().lower() == 'close'
        ):
            active_req = r.get(f"customer:{sender_id}:active_req")
            if active_req:
                r.set(f"req:{active_req}:status", "CLOSED", ex=86400)
                close_request_in_db(active_req, "CLOSED_HIRED")
                response_text = (
                    f"✅ Request *{active_req}* has been closed! Artisans will no longer send proposals.\n\n"
                    "⚠️ *REMINDER:* Do not forget to give your 4-digit Handshake PIN to your hired artisan *only* when the job is fully completed."
                )
                r.delete(f"customer:{sender_id}:active_req")
            else:
                response_text = "⚠️ You don't have any active requests to close."

            send_message(sender_id, response_text)
            return "", 200

        # ==========================================
        # 🚀 ARTISAN INTERCEPTION LOGIC (PROPOSAL)
        # ==========================================
        if msg_type == "text" and text_body_upper.startswith("HND-"):
            ref_id_input = text_body_upper
            customer_id = r.get(f"req:{ref_id_input}:customer")

            if customer_id:
                r.set(state_key, STATE_ARTISAN_PROPOSING, ex=900)
                r.set(f"artisan:{sender_id}:target_req", ref_id_input, ex=900)
                response_text = (
                    f"✅ Request *{ref_id_input}* found.\n\n"
                    "Please type your proposal for the customer. "
                    "Include your estimated price and how soon you can arrive."
                )
            else:
                response_text = "❌ Invalid or expired Reference ID. Please check the group chat and try again."

            send_message(sender_id, response_text)
            return "", 200

        # ==========================================
        # 👷 ARTISAN ONBOARDING "JOIN" TRIGGER
        # ==========================================
        if msg_type == "text" and text_body_upper.strip().lower() == 'join':
            r.set(state_key, STATE_ONB_LOCATION, ex=900)
            response_text = "Welcome to Handees! 🛠️\nLet's get you set up to receive jobs.\n\nWhere is your primary workshop located?\n1️⃣ Akoka\n2️⃣ Yaba\n3️⃣ Bariga\n4️⃣ Other"
            send_message(sender_id, response_text)
            return "", 200

        # ==========================================
        # 🛠️ STATE MACHINE (CUSTOMER & ONBOARDING)
        # ==========================================
        if current_state == STATE_START or (
            msg_type == "text" and text_body.lower() == "reset"
        ):
            r.delete(data_key_cat, data_key_desc, data_key_photo)
            response_text = "Welcome to Handees! 🛠️\nI can help you find a trusted artisan.\n\n1️⃣ Plumber\n2️⃣ Electrician\n3️⃣ Carpenter\n4️⃣ AC/Fridge Repair\n5️⃣ Phone/Laptop Repair\n6️⃣ Other \n\n⚠️ *DISCLAIMER:* Handees connects you with independent artisans. We are not liable for any fraudulent activity, damages or theft. Please remain cautious while interacting with them, supervise work and secure valuables.\n\nReply with the *number* of the service you need to continue:"
            r.set(state_key, STATE_WAITING_CATEGORY, ex=900)

        # --- ARTISAN ONBOARDING STATES ---
        elif current_state == STATE_ONB_LOCATION:
            if msg_type == "text" and text_body in ["1", "2", "3"]:
                loc_map = {"1": "Akoka", "2": "Yaba", "3": "Bariga"}
                r.set(f"onb:{sender_id}:loc", loc_map[text_body], ex=900)
                response_text = (
                    "Great! What is your main skill? (e.g., Plumber, Electrician)"
                )
                r.set(state_key, STATE_ONB_SKILL, ex=900)
            elif msg_type == "text" and text_body == "4":
                response_text = "Sorry, we are currently only onboarding artisans within the Unilag/Akoka/Yaba axis. We will notify you when we expand! 👋"
                r.delete(state_key)
            else:
                response_text = "Please reply with 1, 2, 3, or 4."

        elif current_state == STATE_ONB_SKILL:
            if msg_type == "text":
                r.set(f"onb:{sender_id}:skill", text_body, ex=900)
                response_text = "How many years of experience do you have doing this?"
                r.set(state_key, STATE_ONB_EXP, ex=900)
            else:
                response_text = "Please send text."

        elif current_state == STATE_ONB_EXP:
            if msg_type == "text":
                r.set(f"onb:{sender_id}:exp", text_body, ex=900)
                response_text = "Almost done! 📹\n\nPlease send a short video (max 30 seconds) showing your face and the tools you use for your trade. This proves you are a real professional."
                r.set(state_key, STATE_ONB_VIDEO, ex=900)
            else:
                response_text = "Please send text."

        elif current_state == STATE_ONB_VIDEO:
            if msg_type == "video":
                loc = r.get(f"onb:{sender_id}:loc")
                skill = r.get(f"onb:{sender_id}:skill")
                exp = r.get(f"onb:{sender_id}:exp")

                save_artisan_application(sender_id, loc, skill, exp, video_id)
                form_link = os.getenv(
                    "KYC_FORM_LINK", "https://forms.gle/YOUR_GOOGLE_FORM"
                )
                response_text = f"✅ Video received!\n\nFinal step: Please click this secure link to upload your valid ID and Guarantor details:\n{form_link}\n\nWe will review your profile within 24 hours. If approved, you will automatically receive an invite to our group chat!"
                r.delete(
                    state_key,
                    f"onb:{sender_id}:loc",
                    f"onb:{sender_id}:skill",
                    f"onb:{sender_id}:exp",
                )
            else:
                response_text = (
                    "⚠️ Please send a short video to complete your registration."
                )

        # --- CUSTOMER REQUEST STATES ---
        elif current_state == STATE_WAITING_CATEGORY:
            if text_body in CATEGORIES:
                r.set(data_key_cat, CATEGORIES[text_body], ex=900)
                response_text = f"Got it: *{CATEGORIES[text_body]}*.\n\nPlease type a short description of the issue."
                r.set(state_key, STATE_WAITING_DESCRIPTION, ex=900)
            else:
                response_text = (
                    "⚠️ Invalid number. Please reply with 1, 2, 3, 4, 5, or 6."
                )

        elif current_state == STATE_WAITING_DESCRIPTION:
            if msg_type == "text":
                r.set(data_key_desc, text_body, ex=900)
                response_text = "Thanks. Do you have a photo or video of the issue? 📸\n\n👉 **Send the photo now**.\n👉 Or type **SKIP** if you don't have one."
                r.set(state_key, STATE_WAITING_PHOTO, ex=900)
            else:
                response_text = "Please send a text description first."

        elif current_state == STATE_WAITING_PHOTO:
            has_photo = "No"
            if msg_type == "image":
                r.set(data_key_photo, image_id, ex=900)
                has_photo = "Yes"
            elif msg_type == "text" and text_body.lower() == "skip":
                r.set(data_key_photo, "None", ex=900)
            else:
                send_message(sender_id, "Please send a photo or type 'SKIP'.")
                return "", 200

            cat = r.get(data_key_cat)
            desc = r.get(data_key_desc)

            response_text = f"Please confirm your request details:\n\n🔧 *Service:* {cat}\n📝 *Issue:* {desc}\n📸 *Photo:* {has_photo}\n\nReply *YES* to submit request.\nReply *CANCEL* to start over."
            r.set(state_key, STATE_WAITING_CONFIRMATION, ex=900)

        elif current_state == STATE_WAITING_CONFIRMATION:
            if text_body and text_body.lower() == "yes":
                final_cat = r.get(data_key_cat)
                final_desc = r.get(data_key_desc)
                final_photo = r.get(data_key_photo)

                ref_id = generate_ref_id()
                pin_code = generate_pin()  # <--- NEW PIN

                # Save request and PIN state
                r.set(f"req:{ref_id}:customer", sender_id, ex=86400)
                r.set(f"req:{ref_id}:status", "OPEN", ex=86400)
                r.set(f"req:{ref_id}:pin", pin_code, ex=86400)  # Store the PIN securely
                r.set(f"customer:{sender_id}:active_req", ref_id, ex=86400)

                has_photo_bool = bool(final_photo and final_photo != "None")
                log_request(ref_id, sender_id, final_cat, final_desc, has_photo_bool)

                admin_text = f"🚀 *New Handees Request!* 🚀\n\n🔖 *Ref:* {ref_id}\n🔧 *Service:* {final_cat}\n📝 *Issue:* {final_desc}\n\n👉 *Artisans:* Reply to the bot with *{ref_id}* to bid for this job."
                send_message(ADMIN_NO, admin_text)
                if final_photo and final_photo != "None":
                    send_image(ADMIN_NO, final_photo)

                # Send PIN to Customer
                response_text = (
                    f"✅ Request Received! Your ID is *{ref_id}*.\n\n"
                    f"🔒 *YOUR SECURITY PIN: {pin_code}*\n"
                    "⚠️ Keep this safe! Only give this code to the artisan when the job is fully completed to your satisfaction.\n\n"
                    "We have sent your request to our verified artisans. You will receive their proposals here shortly! ⏳"
                )
                r.delete(state_key, data_key_cat, data_key_desc, data_key_photo)
            else:
                response_text = "❌ Request Cancelled. Type 'Hi' to start over."
                r.delete(state_key, data_key_cat, data_key_desc, data_key_photo)

        # --- ARTISAN PROPOSAL STATE ---
        elif current_state == STATE_ARTISAN_PROPOSING:
            if msg_type == "text":
                target_req = r.get(f"artisan:{sender_id}:target_req")
                customer_id = r.get(f"req:{target_req}:customer")
                req_status = r.get(f"req:{target_req}:status")

                if customer_id and req_status == "OPEN":
                    log_proposal(target_req, sender_id, text_body)

                    # Fetch Profile for ID Card
                    profile = get_artisan_profile(sender_id)
                    if profile:
                        artisan_card = f"👷 *Pro:* Verified {profile.get('skill', 'Artisan')}\n📍 *Base:* {profile.get('location', 'Local')}\n⏳ *Experience:* {profile.get('experience', 'Verified')} years\n🛡️ *Guarantor Status:* Cleared"
                    else:
                        artisan_card = "👷 *Pro:* Handees Verified Artisan\n🛡️ *Guarantor Status:* Cleared"

                    customer_msg = (
                        f"🔔 *New Artisan Proposal!* 🔔\n\n"
                        f"🔖 *For Request:* {target_req}\n"
                        f"{artisan_card}\n\n"
                        f"💬 *Proposal:* {text_body}\n\n"
                        f"👉 *Contact Artisan:* wa.me/{sender_id}\n"
                        "_(If you hire this artisan, reply with *CLOSE* to stop receiving proposals)_"
                    )
                    send_message(customer_id, customer_msg)
                    response_text = "✅ Your proposal has been sent to the customer!"
                elif req_status == "CLOSED":
                    response_text = "❌ Sorry, this request has already been closed by the customer."
                else:
                    response_text = "⚠️ This request has expired or the customer is no longer available."

                r.delete(state_key, f"artisan:{sender_id}:target_req")

        elif msg_type == "text" and text_body.lower() == "cancel":
            response_text = "❌ Session cleared. Type 'Hi' to start over."
            r.delete(state_key, data_key_cat, data_key_desc, data_key_photo)

        if response_text:
            send_message(sender_id, response_text)

        return "", 200
    else:
        print("SIGNATURE MISMATCH")
        return "", 403


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
