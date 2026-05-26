import os
import datetime
import hmac
import redis
import hashlib
import random
import string

from flask_cors import CORS
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from flask import Flask, request, abort

from db_manager import (
    db,
    check_application_eligibility,
    get_pending_merchant_status,
    get_verified_merchant_by_phone,
    get_verified_merchants_by_category,
)
from utils import (
    parse_message,
    send_message,
    ParsedMessage,
    send_template_message,
)

load_dotenv()

token = os.getenv("VERIFY_TOKEN")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PASS = os.getenv("REDIS_PASS")
APP_SECRET = os.getenv("APP_SECRET")
ONBOARDING_FORM_URL = os.getenv("ONBOARDING_FORM_URL", "https://your-merchant-form.com")
ENCRYPT_KEY = os.getenv("ENCRYPT_KEY")

app = Flask(__name__)
r = redis.Redis(
    host=REDIS_HOST, password=REDIS_PASS, port=6379, db=10, decode_responses=True
)
CORS(app, resources={r"/api/*": {"origins": "*"}})
cipher_suite = Fernet(ENCRYPT_KEY.encode())

# --- STATE CONSTANTS ---
STATE_START = "START"
STATE_CHOOSING_ROLE = "CHOOSING_ROLE"

# Customer States
STATE_WAITING_CATEGORY = "WAITING_CATEGORY"
STATE_SELECTING_MERCHANT = "SELECTING_MERCHANT"
STATE_SELECTING_TIME = "SELECTING_TIME"

# Merchant States
STATE_MERCHANT_DASHBOARD = "MERCHANT_DASHBOARD"
STATE_MERCHANT_DECIDING = "MERCHANT_DECIDING"

# --- B2B PIVOT DATA ---
CATEGORIES = {
    "1": "Barbershop / Salon",
    "2": "Mechanic Garage",
    "3": "Spa / Aesthetics",
    "4": "Fashion Designer",
    "5": "Nailtech"
}

# Dummy Database (Now includes Ratings)
DUMMY_MERCHANTS = {
    "Barbershop / Salon": [
        {
            "id": "1",
            "name": "Fresh Cuts",
            "location": "Sabo",
            "phone": "2348000000001",
            "rating": "4.8",
        },
        {
            "id": "2",
            "name": "Elite Clippers",
            "location": "Akoka",
            "phone": "2348000000002",
            "rating": "4.5",
        },
    ],
    "Mechanic Garage": [
        {
            "id": "1",
            "name": "AutoFix Garage",
            "location": "Yaba",
            "phone": "2348000000003",
            "rating": "4.9",
        }
    ],
    "Spa / Aesthetics": [
        {
            "id": "1",
            "name": "Glow Studio",
            "location": "Onike",
            "phone": "2348000000004",
            "rating": "4.7",
        }
    ],
}


def generate_ref_id():
    chars = string.ascii_uppercase + string.digits
    return "BK-" + "".join(random.choices(chars, k=5))


def get_merchant_profile(phone_number):
    """Helper function to check if a phone number belongs to a registered merchant.
    TODO: Swap this out for a Firestore query later."""
    for category, merchants in DUMMY_MERCHANTS.items():
        for m in merchants:
            if m["phone"] == phone_number:
                return m
    return None


@app.get("/")
def parse_data():
    mode = request.args.get("hub.mode")
    verify_token = request.args.get("hub.verify_token")
    if mode == "subscribe" and verify_token == token:
        return request.args.get("hub.challenge"), 200
    return "", 403


@app.post("/api/secure-identity")
def secure_identity():
    """Takes a raw NIN, returns a search hash and an encrypted string."""
    if request.method == "OPTIONS":
        return "", 200

    data = request.get_json(force=True)
    raw_nin = str(data.get("nin", "")).strip()

    if not raw_nin:
        return {"error": "Missing NIN"}, 400

    nin_hash = hashlib.sha256(raw_nin.encode()).hexdigest()
    nin_encrypted = cipher_suite.encrypt(raw_nin.encode()).decode()

    return {"nin_hash": nin_hash, "nin_encrypted": nin_encrypted}, 200


@app.post("/api/reveal-identity")
def reveal_identity():
    """Decrypts the NIN and logs the read-access for NDPA compliance."""
    if request.method == "OPTIONS":
        return "", 200

    data = request.get_json(force=True)
    encrypted_nin = data.get("encrypted_nin")
    admin_email = data.get("admin_email")
    merchant_id = data.get("merchant_id")

    if not encrypted_nin or not admin_email:
        return {"error": "Missing payload data"}, 400

    try:
        # Decrypt the sensitive data
        decrypted_nin = cipher_suite.decrypt(encrypted_nin.encode()).decode()

        # Log the access to Firestore
        log_ref = db.collection("audit_logs").document()
        log_ref.set(
            {
                "action": "DECRYPTED_SENSITIVE_PII",
                "target_merchant_id": merchant_id,
                "accessed_by": admin_email,
                "accessed_at": datetime.datetime.now(datetime.timezone.utc),
                "ip_address": request.remote_addr,
            }
        )

        return {"nin": decrypted_nin}, 200
    except Exception as e:
        print(f"Decryption/Logging Error: {e}")
        return {"error": "Secure read failed"}, 403


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
                msg_type = parsed.msg_type
            else:
                return "ok", 200
        except (KeyError, IndexError):
            return "ignored", 200

        state_key = f"handees:{sender_id}:state"
        current_state = r.get(state_key) or STATE_START

        response_text = ""
        text_body_upper = text_body.strip().upper() if text_body else ""

        # --- GLOBAL RESET ---
        if msg_type == "text" and text_body_upper == "RESET":
            # Clear all potential session data
            r.delete(
                state_key,
                f"handees:{sender_id}:category",
                f"customer:{sender_id}:selected_merchant",
                f"merchant:{sender_id}:pending_booking",
            )
            current_state = STATE_START

        # ==========================================
        # 🛠️ STATE MACHINE ROUTER
        # ==========================================

        # --- STEP 1: WELCOME & ROLE SELECTION ---
        if current_state == STATE_START:
            response_text = (
                "Welcome to Handees! 📅 \n\n"
                "How can we help you today?\n"
                "Reply *1* - I want to book a service\n"
                "Reply *2* - I am a Merchant / Business Owner"
            )
            r.set(state_key, STATE_CHOOSING_ROLE, ex=900)

        # --- STEP 2: ROUTING LOGIC ---
        elif current_state == STATE_CHOOSING_ROLE:
            if text_body == "1":
                # Route to Customer Flow
                response_text = (
                    "What are you looking for today?\n"
                    "1️⃣ Barbershop / Salon\n"
                    "2️⃣ Mechanic Garage\n"
                    "3️⃣ Spa / Aesthetics\n"
                    "4️⃣ Fashion Designer\n"
                    "5️⃣ Nailtech\n\n"
                    "Reply with a *number*:"
                )
                r.set(state_key, STATE_WAITING_CATEGORY, ex=900)

            elif text_body == "2":
                # Route to Merchant Flow
                profile = get_verified_merchant_by_phone(sender_id)
                if profile:
                    # Existing Approved Merchant -> Standard Dashboard Only (No status check needed)
                    response_text = (
                        f"Welcome back, *{profile['name']}*! 🏬\n\n"
                        "Reply *1* - View Active Bookings\n"
                        "Reply *2* - View My Rating"
                    )
                    r.set(state_key, STATE_MERCHANT_DASHBOARD, ex=900)
                else:
                    # Unapproved or Pending Merchant -> Look up application in Firestore
                    app_status, rejection_reason = get_pending_merchant_status(
                        sender_id
                    )

                    if app_status == "pending_review":
                        response_text = (
                            "⏳ *Application Status: Under Review*\n\n"
                            "Our compliance team is currently reviewing your 10-second storefront verification video.\n\n"
                            "Reply *CHECK* to re-run an eligibility status query onto your profile."
                        )
                        r.set(state_key, "MERCHANT_STATUS_CHECK", ex=900)

                    elif app_status == "rejected":
                        response_text = (
                            f"❌ *Application Status: Denied*\n"
                            f"Reason: {rejection_reason}\n\n"
                            "Reply *CHECK* to see if your 7-day restriction cooldown has cleared to re-apply."
                        )
                        r.set(state_key, "MERCHANT_STATUS_CHECK", ex=900)

                    else:
                        # Brand new user with completely no history entries
                        response_text = (
                            "Ready to grow your business? 🚀\n\n"
                            "Partner with Handees to get premium bookings directly through WhatsApp. "
                            "Click the secure link below to submit your business details for verification:\n"
                            f"🔗 {ONBOARDING_FORM_URL}\n\n"
                            "*Note: Once approved, your shop will automatically appear to customers here.*"
                        )
                        r.delete(state_key)
            else:
                response_text = "⚠️ Please reply with 1 or 2."

        # ==========================================
        # 🏢 MERCHANT DASHBOARD FLOW
        # ==========================================
        elif current_state == STATE_MERCHANT_DASHBOARD:
            profile = get_verified_merchant_by_phone(sender_id)
            if text_body == "1":
                # Check Redis for a pending booking for this specific merchant
                pending_booking = r.get(f"merchant:{sender_id}:pending_booking")
                if pending_booking:
                    time = r.get(f"booking:{pending_booking}:time")
                    response_text = f"📅 You have a pending request!\n🔖 Ref: {pending_booking}\n⏰ Time: {time}\n\nReply ACCEPT or REJECT to that message."
                else:
                    response_text = "📅 You currently have no pending booking requests. Keep an eye out!"
                r.set(state_key, STATE_START, ex=900)

            elif text_body == "2":
                response_text = f"⭐ *Your Shop Rating:* {profile['rating']} / 5.0\n\nGreat job keeping your customers happy!"
                r.set(state_key, STATE_START, ex=900)
            else:
                response_text = "⚠️ Please reply with 1 or 2."

        # ==========================================
        # 🔍 UNAPPROVED MERCHANT STATUS CHECKER
        # ==========================================
        elif current_state == "MERCHANT_STATUS_CHECK":
            if text_body_upper == "CHECK":
                # Look up latest app data parameters to fetch their NIN
                local_phone = sender_id.replace("+", "")
                if local_phone.startswith("234") and len(local_phone) == 13:
                    local_phone = "0" + local_phone[3:]

                # Fetch their record profile entry
                from db_manager import db

                query = (
                    db.collection("pending_merchants")
                    .where("businessDetails.phone", "==", local_phone)
                    .order_by("createdAt", direction=db.Query.DESCENDING)
                    .limit(1)
                )
                docs = query.stream()
                latest_app = next(docs, None)

                if latest_app:
                    nin = latest_app.to_dict().get("ownerDetails", {}).get("nin")
                    # Fire execution check logic matching the main gating engine rules
                    is_eligible, message = check_application_eligibility(nin)

                    if is_eligible:
                        response_text = f"✅ *Good news!* You are fully eligible to apply. Link your storefront here: {ONBOARDING_FORM_URL}"
                    else:
                        response_text = f"📋 *System Assessment Update:*\n{message}"
                else:
                    response_text = "⚠️ No application data profile found connected to this number. Type RESET to start fresh."

                r.set(state_key, STATE_START, ex=900)
            else:
                response_text = "⚠️ Invalid command. Please reply with *CHECK* or type *RESET* to go back to the main menu."

        # ==========================================
        # 🧑‍🔧 CUSTOMER FLOW
        # ==========================================
        elif current_state == STATE_WAITING_CATEGORY:
            if text_body in CATEGORIES:
                selected_cat = CATEGORIES[text_body]
                r.set(f"handees:{sender_id}:category", selected_cat, ex=900)

                # Fetch from live Firestore collection
                merchants = get_verified_merchants_by_category(selected_cat)

                if not merchants:
                    response_text = f"No verified shops found for {selected_cat} yet. Type 'RESET' to start over."
                else:
                    msg_lines = [
                        f"Here are the verified {selected_cat} shops near you:\n"
                    ]

                    # Inject dynamic list
                    for m in merchants:
                        msg_lines.append(
                            f"*{m['id']}* - {m['name']} ({m['location']}) • ⭐ {m.get('rating', '5.0')}"
                        )

                    msg_lines.append(
                        "\nReply with the *ID* (e.g., A7F9B) of the shop to book:"
                    )
                    response_text = "\n".join(msg_lines)
                    r.set(state_key, STATE_SELECTING_MERCHANT, ex=900)
            else:
                response_text = (
                    "⚠️ Invalid selection. Please reply with 1, 2, 3, 4, or 5."
                )

        elif current_state == STATE_SELECTING_MERCHANT:
            selected_cat = r.get(f"handees:{sender_id}:category")
            merchants = get_verified_merchants_by_category(selected_cat)

            # Match against the short ID
            selected_merchant = next((m for m in merchants if m["id"] == text_body_upper), None)

            if selected_merchant:
                # Format phone to international for WhatsApp routing
                raw_phone = selected_merchant["phone"]
                if raw_phone.startswith("0"):
                    routing_phone = "234" + raw_phone[1:]
                else:
                    routing_phone = raw_phone

                r.set(f"customer:{sender_id}:selected_merchant", routing_phone, ex=900)
                response_text = (
                    f"Great! You selected *{selected_merchant['name']}*.\n\n"
                    f"What time would you like to book for today? (e.g., *2:00 PM* or *Now*)"
                )
                r.set(state_key, STATE_SELECTING_TIME, ex=900)
            else:
                response_text = "⚠️ Invalid shop ID. Please try again."

        elif current_state == STATE_SELECTING_TIME:
            requested_time = text_body.strip()
            merchant_phone = r.get(f"customer:{sender_id}:selected_merchant")

            if merchant_phone:
                # Save the requested time temporarily
                r.set(f"customer:{sender_id}:temp_time", requested_time, ex=900)

                response_text = (
                    f"Almost done! You are requesting an appointment for *{requested_time}*.\n\n"
                    f"⚖️ *Terms of Service:*\n"
                    f"Handees is a booking directory. We do not provide the services and are not liable for interactions or disputes with the merchant.\n\n"
                    f"Reply *YES* to accept these terms and send your booking request.\n"
                    f"Reply *CANCEL* to stop."
                )
                r.set(state_key, "WAITING_TERMS_CONFIRMATION", ex=900)
            else:
                response_text = "⚠️ Session expired. Please type 'RESET' to start over."

        # --- STEP 5: LOG CONSENT & TRIGGER BOOKING ---
        elif current_state == "WAITING_TERMS_CONFIRMATION":
            if text_body_upper == "YES":
                merchant_phone = r.get(f"customer:{sender_id}:selected_merchant")
                requested_time = r.get(f"customer:{sender_id}:temp_time")

                booking_id = generate_ref_id()
                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # 1. Log the Booking & Consent in Redis (Eventually move to Firestore)
                r.set(f"booking:{booking_id}:customer", sender_id, ex=86400)
                r.set(f"booking:{booking_id}:time", requested_time, ex=86400)
                r.set(f"booking:{booking_id}:terms_accepted", "true", ex=86400)
                r.set(f"booking:{booking_id}:consent_timestamp", timestamp, ex=86400)

                # 2. Ping Customer
                send_message(
                    sender_id,
                    f"✅ Terms accepted. Contacting the shop to confirm {requested_time}. Please wait...",
                )
                r.set(state_key, STATE_START, ex=900)

                # 3. Ping Merchant
                r.set(
                    f"handees:{merchant_phone}:state", STATE_MERCHANT_DECIDING, ex=900
                )
                r.set(f"merchant:{merchant_phone}:pending_booking", booking_id, ex=900)

                merchant_msg = (
                    f"🔔 *New Booking Request!*\n\n"
                    f"🔖 *Ref:* {booking_id}\n"
                    f"⏰ *Time:* {requested_time}\n"
                    f"📱 *Customer:* wa.me/{sender_id.replace('+', '')}\n\n"
                    f"Reply *ACCEPT* to confirm this appointment.\n"
                    f"Reply *REJECT* if you are fully booked."
                )
                send_message(merchant_phone, merchant_msg)
                return "", 200

            elif text_body_upper == "CANCEL":
                response_text = "❌ Booking cancelled. Type 'RESET' to start over."
                r.set(state_key, STATE_START, ex=900)
            else:
                response_text = "⚠️ Please reply strictly with *YES* or *CANCEL*."

        # --- MERCHANT DECISION (INTERCEPT) ---
        elif current_state == STATE_MERCHANT_DECIDING:
            pending_booking_id = r.get(f"merchant:{sender_id}:pending_booking")

            if not pending_booking_id:
                response_text = "⚠️ You have no pending bookings."
                r.set(state_key, STATE_START, ex=900)
            else:
                customer_id = r.get(f"booking:{pending_booking_id}:customer")
                requested_time = r.get(f"booking:{pending_booking_id}:time")

                if text_body_upper == "ACCEPT":
                    send_message(
                        sender_id,
                        f"✅ Booking {pending_booking_id} confirmed and added to your schedule!",
                    )
                    if customer_id:
                        send_message(
                            customer_id,
                            f"🎉 *Confirmed!* The shop has accepted your appointment for {requested_time}. See you there!",
                        )
                elif text_body_upper == "REJECT":
                    send_message(
                        sender_id,
                        f"❌ Booking {pending_booking_id} rejected. We will let the customer know.",
                    )
                    if customer_id:
                        send_message(
                            customer_id,
                            f"⚠️ The shop is currently fully booked for {requested_time}. Type 'RESET' to select a different shop or time.",
                        )
                else:
                    send_message(
                        sender_id, "Please reply strictly with *ACCEPT* or *REJECT*."
                    )
                    return "", 200

                r.delete(state_key, f"merchant:{sender_id}:pending_booking")
                return "", 200

        if response_text:
            send_message(sender_id, response_text)

        return "", 200
    else:
        print("SIGNATURE MISMATCH")
        return "", 403


@app.get("/api/check-eligibility/<string:nin>")
def api_check_eligibility(nin):
    # This calls your underlying database check logic
    is_eligible, message = check_application_eligibility(nin)
    return {"eligible": is_eligible, "message": message}, 200


@app.post("/api/notify-verdict")
def notify_verdict():
    data = request.get_json(force=True)
    merchant_phone = data.get("phone")
    merchant_name = data.get("name")
    status = data.get("status")
    reason = data.get("reason", "Not specified")

    if not merchant_phone:
        return {"error": "Phone number missing"}, 400

    # Clean the phone number format for Meta's Graph API
    formatted_phone = merchant_phone.replace("+", "").replace(" ", "")

    if status == "approved":
        # Fires sequentially matching {{1}} -> Name
        send_template_message(
            to_number=formatted_phone,
            template_name="merchant_approval",
            params_dict={"name": merchant_name},
        )
    elif status == "rejected":
        # Fires sequentially matching {{1}} -> Name, {{2}} -> Reason
        send_template_message(
            to_number=formatted_phone,
            template_name="merchant_disapproval",
            params_dict={"name": merchant_name, "reason": reason},
        )

    return {"status": "success"}, 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
