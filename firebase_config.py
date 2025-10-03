import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import os
import logging

def initialize_firebase():
    """
    Initializes the Firebase Admin SDK.

    This function uses the `GOOGLE_APPLICATION_CREDENTIALS` environment variable
    for the service account key file and `FIREBASE_DATABASE_URL` for the database URL.
    """
    try:
        # The `GOOGLE_APPLICATION_CREDENTIALS` environment variable is automatically
        # used by the `credentials.ApplicationDefault()` method.
        cred = credentials.ApplicationDefault()

        database_url = os.environ.get('FIREBASE_DATABASE_URL')
        if not database_url:
            raise ValueError("The FIREBASE_DATABASE_URL environment variable must be set.")

        firebase_admin.initialize_app(cred, {
            'databaseURL': database_url
        })
        logging.info("Firebase Admin SDK initialized successfully.")
        return True
    except Exception as e:
        logging.error(f"Error initializing Firebase Admin SDK: {e}")
        logging.error("Please ensure that GOOGLE_APPLICATION_CREDENTIALS and FIREBASE_DATABASE_URL are set correctly.")
        return False