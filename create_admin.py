#!/usr/bin/env python3
"""
Admin Initialization Script
Run this script to create the first superadmin user and set up the admin system.
"""

import os
import sys
from pymongo import MongoClient
from services.admin_service import AdminService
from models.admin import Admin

from dotenv import load_dotenv

load_dotenv()

def create_initial_superadmin():
    """Create the first superadmin user"""
    print("=== Admin System Initialization ===")
    print("This script will create the first superadmin user.")
    print()

    # Get database connection
    mongo_uri = os.environ.get(
        'MONGODB_URI', 'mongodb://localhost:27017/chatbot')
    print(mongo_uri)
    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    admin_service = AdminService(db)

    # Check if any superadmin already exists
    existing_superadmins = admin_service.get_admins_by_role('superadmin')
    if existing_superadmins:
        print("A superadmin already exists. Current superadmins:")
        for admin in existing_superadmins:
            print(f"  - {admin.username} (Status: {admin.status})")
        print()

        create_another = input(
            "Do you want to create another superadmin? (y/N): ").lower().strip()
        if create_another != 'y':
            print("Initialization cancelled.")
            return

    print("Creating initial superadmin...")
    print()

    # Get superadmin details
    while True:
        username = input("Enter superadmin username: ").strip()
        if not username:
            print("Username cannot be empty!")
            continue

        if admin_service.get_admin_by_username(username):
            print("Username already exists! Please choose a different username.")
            continue

        break

    while True:
        password = input(
            "Enter superadmin password (min 8 characters): ").strip()
        if len(password) < 8:
            print("Password must be at least 8 characters long!")
            continue

        confirm_password = input("Confirm password: ").strip()
        if password != confirm_password:
            print("Passwords don't match!")
            continue

        break

    email = input("Enter email (optional): ").strip() or None
    phone = input("Enter phone (optional): ").strip() or None

    # Create the superadmin
    try:
        superadmin = admin_service.create_admin(
            username=username,
            password=password,
            role='superadmin',
            email=email,
            phone=phone
        )

        print()
        print("✅ Superadmin created successfully!")
        print(f"   Username: {superadmin.username}")
        print(f"   Role: {superadmin.role}")
        print(f"   Admin ID: {superadmin.admin_id}")
        print(f"   Email: {superadmin.email or 'Not provided'}")
        print(f"   Phone: {superadmin.phone or 'Not provided'}")
        print()
        print("You can now login to the admin panel with these credentials.")

    except Exception as e:
        print(f"❌ Error creating superadmin: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    create_initial_superadmin()
