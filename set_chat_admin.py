#!/usr/bin/env python3
"""
Chat Admin Assignment Script
Run this script to assign an admin to all chats that don't have an admin_id.
"""
import os
import sys
from pymongo import MongoClient
from services.admin_service import AdminService
from models.admin import Admin

from dotenv import load_dotenv

load_dotenv()

def assign_admin_to_chats():
    """Assign selected admin to chats without admin_id"""
    # print("=== Chat Admin Assignment Script ===")
    # print("This script will assign an admin to all chats that don't have an admin_id.")
    # print()

    # Get database connection
    mongo_uri = os.environ.get(
        'MONGODB_URI', 'mongodb://localhost:27017/chatbot')
    # print(mongo_uri)
    client = MongoClient(mongo_uri)
    db = client.get_default_database()
    admin_service = AdminService(db)

    # Get all admins with role 'admin'
    # print("Fetching admins with role 'admin'...")
    admins = admin_service.get_admins_by_role('admin')

    if not admins:
        # print("❌ No admins found with role 'admin'.")
        # print("Please create an admin user first or check if admins exist.")
        sys.exit(1)

    # Display available admins
    # print(f"\nFound {len(admins)} admin(s):")
    # print()
    for i, admin in enumerate(admins, 1):
        status_emoji = "✅" if admin.status == "active" else "❌"
        # print(f"  {i}. {admin.username} (ID: {admin.admin_id}) {status_emoji}")
        # print(f"     Email: {admin.email or 'Not provided'}")
        # print(f"     Phone: {admin.phone or 'Not provided'}")
        # print(f"     Status: {admin.status}")
        # print(f"     Created: {admin.created_at}")
        # print()

    # Let user select an admin
    while True:
        try:
            choice = input(f"Select an admin (1-{len(admins)}): ").strip()
            if not choice:
                # print("Please enter a number!")
                continue

            choice_num = int(choice)
            if 1 <= choice_num <= len(admins):
                selected_admin = admins[choice_num - 1]
                break
            else:
                # print(f"Please enter a number between 1 and {len(admins)}!")
                continue
        except ValueError:
            # print("Please enter a valid number!")
            continue

    # print(f"\nSelected admin: {
          selected_admin.username} (ID: {selected_admin.admin_id})")

    # Confirm selection
    confirm = input("\nProceed with this admin? (y/N): ").lower().strip()
    if confirm != 'y':
        # print("Operation cancelled.")
        return

    # Check for chats without admin_id
    # print("\nChecking chats collection...")
    chats_collection = db.chats  # Assuming chats collection name

    # Count chats without admin_id
    chats_without_admin = chats_collection.count_documents({
        "$or": [
            {"admin_id": {"$exists": False}},
            {"admin_id": None},
            {"admin_id": ""}
        ]
    })

    if chats_without_admin == 0:
        # print("✅ All chats already have an admin_id assigned.")
        return

    # print(f"Found {chats_without_admin} chat(s) without admin_id.")

    # Final confirmation
    confirm_update = input(f"\nAssign admin '{selected_admin.username}' to {
                           chats_without_admin} chat(s)? (y/N): ").lower().strip()
    if confirm_update != 'y':
        # print("Operation cancelled.")
        return

    # Update chats
    try:
        # print("\nUpdating chats...")
        result = chats_collection.update_many(
            {
                "$or": [
                    {"admin_id": {"$exists": False}},
                    {"admin_id": None},
                    {"admin_id": ""}
                ]
            },
            {
                "$set": {
                    "admin_id": selected_admin.admin_id,
                    "updated_at": None  # You might want to set current timestamp here
                }
            }
        )

        # print(f"✅ Successfully updated {result.modified_count} chat(s)!")
        # print(f"   Admin assigned: {
              selected_admin.username} (ID: {selected_admin.admin_id})")
        # print()

        # Show summary
        total_chats = chats_collection.count_documents({})
        chats_with_admin = chats_collection.count_documents({
            "admin_id": {"$exists": True, "$ne": None, "$ne": ""}
        })

        # print("=== Summary ===")
        # print(f"Total chats in database: {total_chats}")
        # print(f"Chats with admin assigned: {chats_with_admin}")
        # print(f"Chats without admin: {total_chats - chats_with_admin}")

    except Exception as e:
        # print(f"❌ Error updating chats: {str(e)}")
        sys.exit(1)


def main():
    """Main function"""
    try:
        assign_admin_to_chats()
    except KeyboardInterrupt:
        # print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        # print(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
