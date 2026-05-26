import hashlib
from datetime import datetime, timezone

from google.cloud import firestore
from firebase_admin import firestore

db = firestore.Client()


def hash_phone(phone_number):
    return hashlib.sha256(phone_number.encode()).hexdigest()


def log_request(ref_id, phone, category, description, has_photo):
    try:
        doc_ref = db.collection("service_requests").document(ref_id)
        doc_ref.set(
            {
                "ref_id": ref_id,
                "customer_phone_hash": hash_phone(phone),
                "category": category,
                "raw_description": description,
                "has_photo": has_photo,
                "status": "OPEN",  # <--- NEW FIELD
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception as e:
        print(f"Firestore Error: {e}")


def log_proposal(ref_id, artisan_phone, proposal_text):
    try:
        doc_ref = db.collection("artisan_proposals").document()
        doc_ref.set(
            {
                "request_ref": ref_id,
                "artisan_phone_hash": hash_phone(artisan_phone),
                "proposal_text": proposal_text,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception as e:
        print(f"Firestore Error: {e}")


def close_request_in_db(ref_id, resolution="CLOSED_HIRED"):
    """Updates the status of a request to stop receiving bids"""
    try:
        doc_ref = db.collection("service_requests").document(ref_id)
        doc_ref.update({"status": resolution, "closed_at": firestore.SERVER_TIMESTAMP})
    except Exception as e:
        print(f"Firestore Error: {e}")


def save_artisan_application(phone, location, skill, experience, video_id):
    """Saves a new artisan application to Firestore for admin review"""
    try:
        # We don't hash the phone here because the Admin needs to see it to approve it
        doc_ref = db.collection("artisan_applications").document(phone)
        doc_ref.set(
            {
                "phone": phone,
                "location": location,
                "skill": skill,
                "experience": experience,
                "video_id": video_id,  # Can be used later if you want to pull the video via Meta API
                "status": "PENDING",
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception as e:
        print(f"Firestore Error: {e}")


def _format_phone_for_db(whatsapp_phone):
    """
    Helper function to convert international WhatsApp format (23480...)
    to the local Nigerian format (080...) stored in Firestore.
    """
    phone = str(whatsapp_phone).replace("+", "")
    if phone.startswith("234") and len(phone) == 13:
        return "0" + phone[3:]
    return phone


def get_artisan_profile(phone):
    """Fetches an artisan's profile from Firestore to create their ID card"""
    try:
        local_phone = _format_phone_for_db(phone)
        query = (
            db.collection("pending_artisans")
            .where("personalDetails.phoneNumber", "==", local_phone)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1)
        )

        docs = query.stream()
        latest_doc = next(docs, None)

        if latest_doc:
            return latest_doc.to_dict()

    except Exception as e:
        print(f"Firestore Error getting profile: {e}")

    return None


def approve_artisan_in_db(phone):
    """Marks an artisan application as approved via the WhatsApp Bot Fallback"""
    try:
        local_phone = _format_phone_for_db(phone)

        # Find the document first
        query = (
            db.collection("pending_artisans")
            .where("personalDetails.phoneNumber", "==", local_phone)
            .limit(1)
        )

        docs = query.stream()
        doc_to_update = next(docs, None)

        if doc_to_update:
            doc_to_update.reference.update(
                {
                    "status": "approved",
                    "audit.verdictMadeAt": firestore.SERVER_TIMESTAMP,
                    "audit.verdictMadeBy": "WhatsApp Bot (Manual Command)",
                }
            )
            return True

    except Exception as e:
        print(f"Firestore Error approving artisan: {e}")

    return False


def complete_request_in_db(ref_id, artisan_phone):
    """Logs the final completion of a job after a successful PIN handshake"""
    try:
        doc_ref = db.collection("service_requests").document(ref_id)
        doc_ref.update(
            {
                "status": "COMPLETED",
                "hired_artisan": hash_phone(artisan_phone),
                "completed_at": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception as e:
        print(f"Firestore Error: {e}")


def get_pending_merchant_status(phone_number):
    """
    Fetches the latest onboarding application status for a given phone number.
    Returns: (status: str/None, reason: str/None)
    """
    try:
        # Format the phone number to local 080... format to match web form storage
        local_phone = _format_phone_for_db(phone_number)

        query = (
            db.collection("pending_merchants")
            .where("businessDetails.phone", "==", local_phone)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        docs = query.stream()
        latest_app = next(docs, None)

        if latest_app:
            data = latest_app.to_dict()
            status = data.get("status", "pending_review")
            audit = data.get("audit", {})
            reason = audit.get("rejectionReason", "Not specified")
            return status, reason
            
        return None, None
    except Exception as e:
        print(f"Firestore Error tracking merchant app: {e}")
        return None, None


# def check_application_eligibility(nin):
#     """
#     Checks if an artisan is allowed to submit a new application based on their NIN.
#     Returns: (is_eligible: bool, message: str)
#     """
#     # 1. Fetch the most recent application for this NIN
#     query = (
#         db.collection("pending_artisans")
#         .where("personalDetails.nin", "==", nin)
#         .order_by("createdAt", direction=firestore.Query.DESCENDING)
#         .limit(1)
#     )

#     docs = query.stream()
#     latest_app = next(docs, None)

#     # If no record exists, they are good to go
#     if not latest_app:
#         return True, "Eligible"

#     data = latest_app.to_dict()
#     status = data.get("status", "pending_review")

#     # --- RULE 1: Already Pending ---
#     if status == "pending_review":
#         return (
#             False,
#             "You already have an application under review. Please wait for our team to contact you.",
#         )

#     # --- RULE 2: Already Approved ---
#     if status == "approved":
#         return False, "This NIN is already registered to an active Handees artisan."

#     # --- RULE 3: Rejected (The Cooldown Logic) ---
#     if status == "rejected":
#         audit = data.get("audit", {})
#         verdict_time = audit.get("verdictMadeAt")
#         reason = audit.get("rejectionReason", "")

#         # A. Severe Infractions (Permanent Ban)
#         critical_flags = ["Fake Guarantor", "Invalid NIN", "Identity Mismatch"]
#         if any(flag in reason for flag in critical_flags):
#             return (
#                 False,
#                 "This NIN has been flagged by our compliance team and cannot be used.",
#             )

#         # B. Minor Infractions (7-Day Cooldown)
#         if verdict_time:
#             # Convert Firestore Datetime to timezone-aware UTC
#             verdict_date = verdict_time.replace(tzinfo=timezone.utc)
#             days_since_rejection = (datetime.now(timezone.utc) - verdict_date).days

#             COOLDOWN_DAYS = 7  # Much better for pilot growth than 30 days

#             if days_since_rejection < COOLDOWN_DAYS:
#                 days_left = COOLDOWN_DAYS - days_since_rejection
#                 return (
#                     False,
#                     f"Application rejected due to: {reason}. Please fix this and try again in {days_left} days.",
#                 )

#     return True, "Eligible"


def get_merchants_by_category(category_name):
    """Fetches verified merchants for a specific category from Firestore."""
    try:
        merchants_ref = db.collection("verified_merchants")
        # Query where the category matches the user's selection
        query = merchants_ref.where("category", "==", category_name).stream()

        merchants = []
        for doc in query:
            merchants.append(doc.to_dict())

        return merchants
    except Exception as e:
        print(f"Error fetching merchants: {e}")
        return []


def check_application_eligibility(nin):
    """
    Checks if a merchant is allowed to submit a new application based on their NIN.
    Returns: (is_eligible: bool, message: str)
    """
    try:
        # 1. Fetch the most recent application for this NIN using the new B2B structure
        query = (
            db.collection("pending_merchants")
            .where("ownerDetails.nin", "==", str(nin).strip())
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1)
        )

        docs = query.stream()
        latest_app = next(docs, None)

        # If no record exists, they are good to go
        if not latest_app:
            return True, "Eligible"

        data = latest_app.to_dict()
        status = data.get("status", "pending_review")

        # --- RULE 1: Already Pending Review ---
        if status == "pending_review":
            return (
                False,
                "Your business profile is already under review. We will contact you via WhatsApp shortly.",
            )

        # --- RULE 2: Already Approved ---
        if status == "approved":
            return (
                False,
                "This NIN is already registered to an active Handees partner outlet.",
            )

        # --- RULE 3: Rejected (The Cooldown Logic) ---
        if status == "rejected":
            audit = data.get("audit", {})
            verdict_time = audit.get("verdictMadeAt")
            reason = audit.get("rejectionReason", "Details not specified")

            # A. Severe Infractions (Permanent Ban)
            critical_flags = [
                "Fake Profile",
                "Invalid NIN",
                "Identity Mismatch",
                "Fraudulent Outlet",
            ]
            if any(flag.lower() in reason.lower() for flag in critical_flags):
                return (
                    False,
                    "This identity has been permanently flagged by our compliance team and cannot be registered.",
                )

            # B. Minor Infractions (7-Day Cooldown for missing info/bad video)
            if verdict_time:
                # Convert Firestore Datetime to timezone-aware UTC
                verdict_date = verdict_time.replace(tzinfo=timezone.utc)
                days_since_rejection = (datetime.now(timezone.utc) - verdict_date).days

                COOLDOWN_DAYS = 7

                if days_since_rejection < COOLDOWN_DAYS:
                    days_left = COOLDOWN_DAYS - days_since_rejection
                    return (
                        False,
                        f"Application was rejected due to: {reason}. Please fix the issue and try again in {days_left} days.",
                    )

        return True, "Eligible"

    except Exception as e:
        print(f"Firestore Error during eligibility check: {e}")
        # Fail safe if database errors out so you don't block legitimate users during pilot testing
        return True, "Eligible"
