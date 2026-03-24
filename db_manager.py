# # db_manager.py
# import sqlite3
# import hashlib
# from datetime import datetime

# DB_FILE = "handees_data.db"


# def init_db():
#     conn = sqlite3.connect(DB_FILE)
#     c = conn.cursor()
#     # Create Requests Table
#     c.execute(
#         """
#         CREATE TABLE IF NOT EXISTS service_requests (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             ref_id TEXT UNIQUE,
#             customer_phone_hash TEXT,
#             category TEXT,
#             raw_description TEXT,
#             has_photo BOOLEAN,
#             created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#         )
#     """
#     )
#     # Create Proposals Table
#     c.execute(
#         """
#         CREATE TABLE IF NOT EXISTS artisan_proposals (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             request_ref TEXT,
#             artisan_phone_hash TEXT,
#             proposal_text TEXT,
#             created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#         )
#     """
#     )
#     conn.commit()
#     conn.close()


# def hash_phone(phone_number):
#     """Anonymize phone numbers for AI training datasets"""
#     return hashlib.sha256(phone_number.encode()).hexdigest()


# def log_request(ref_id, phone, category, description, has_photo):
#     conn = sqlite3.connect(DB_FILE)
#     c = conn.cursor()
#     c.execute(
#         """
#         INSERT INTO service_requests (ref_id, customer_phone_hash, category, raw_description, has_photo)
#         VALUES (?, ?, ?, ?, ?)
#     """,
#         (ref_id, hash_phone(phone), category, description, has_photo),
#     )
#     conn.commit()
#     conn.close()


# def log_proposal(ref_id, artisan_phone, proposal_text):
#     conn = sqlite3.connect(DB_FILE)
#     c = conn.cursor()
#     c.execute(
#         """
#         INSERT INTO artisan_proposals (request_ref, artisan_phone_hash, proposal_text)
#         VALUES (?, ?, ?)
#     """,
#         (ref_id, hash_phone(artisan_phone), proposal_text),
#     )
#     conn.commit()
#     conn.close()

# firestore_db.py
import hashlib
from google.cloud import firestore

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


def approve_artisan_in_db(phone):
    """Marks an artisan application as approved"""
    try:
        doc_ref = db.collection("artisan_applications").document(phone)
        doc_ref.update(
            {"status": "APPROVED", "approved_at": firestore.SERVER_TIMESTAMP}
        )
    except Exception as e:
        print(f"Firestore Error: {e}")


def get_artisan_profile(phone):
    """Fetches an artisan's profile from Firestore to create their ID card"""
    try:
        doc = db.collection("artisan_applications").document(phone).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"Firestore Error: {e}")
    return None


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
