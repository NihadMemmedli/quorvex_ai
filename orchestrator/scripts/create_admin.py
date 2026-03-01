#!/usr/bin/env python3
"""
Script to create the first admin user and optionally migrate existing data.

Usage:
    python orchestrator/scripts/create_admin.py --email admin@example.com --password SecurePass123!

Options:
    --email           Admin user email address
    --password        Admin user password (must meet strength requirements)
    --name            Optional full name for the admin user
    --migrate         Also migrate existing projects to be owned by the admin
    --force-password  Update password if user already exists
"""

import argparse
import sys
from pathlib import Path

# Add orchestrator to path
orchestrator_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(orchestrator_dir))

from sqlmodel import Session, select

from api.db import engine, init_db
from api.models_auth import ProjectMember, User
from api.models_db import Project
from api.security import hash_password, is_password_strong


def create_admin_user(email: str, password: str, full_name: str = None, force_password: bool = False) -> User:
    """Create the first admin/superuser account."""

    # Validate password
    is_strong, error = is_password_strong(password)
    if not is_strong:
        print(f"Error: {error}")
        sys.exit(1)

    with Session(engine) as session:
        # Check if email already exists
        existing = session.exec(select(User).where(User.email == email.lower())).first()

        if existing:
            print(f"User with email {email} already exists.")
            if force_password:
                print("Updating password...")
                existing.password_hash = hash_password(password)
                existing.failed_login_attempts = 0  # Reset lockout
                existing.locked_until = None
                session.commit()
                print("Password updated successfully.")
            if not existing.is_superuser:
                print("Promoting user to superuser...")
                existing.is_superuser = True
                session.commit()
            else:
                print("User is already a superuser.")
            return existing

        # Create new admin user
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            is_superuser=True,
            is_active=True,
            email_verified=True,  # Admin is pre-verified
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        print(f"Created admin user: {user.email} (id={user.id})")
        return user


def migrate_existing_data(admin_user: User):
    """Add admin user as project admin for all existing projects."""

    with Session(engine) as session:
        # Get all projects
        projects = session.exec(select(Project)).all()

        if not projects:
            print("No projects found.")
            return

        print(f"Found {len(projects)} projects to check.")
        added_count = 0

        for project in projects:
            # Add admin as project admin if not already a member
            existing_member = session.exec(
                select(ProjectMember)
                .where(ProjectMember.project_id == project.id)
                .where(ProjectMember.user_id == admin_user.id)
            ).first()

            if not existing_member:
                member = ProjectMember(project_id=project.id, user_id=admin_user.id, role="admin")
                session.add(member)
                print(f"  + Added admin to '{project.name}'")
                added_count += 1
            else:
                print(f"  - '{project.name}' already has admin access")

        session.commit()
        print(f"Migration complete: Added admin to {added_count} projects.")


def add_all_users_to_default_project():
    """Add all existing users to the Default Project with viewer role.

    This is a one-time migration to ensure existing users can see at least
    the Default Project after enabling project membership filtering.
    """
    DEFAULT_PROJECT_ID = "default"

    with Session(engine) as session:
        # Ensure default project exists
        default_project = session.get(Project, DEFAULT_PROJECT_ID)
        if not default_project:
            print("Default project not found. Creating it...")
            default_project = Project(
                id=DEFAULT_PROJECT_ID,
                name="Default Project",
                description="Default project for all existing and new content",
            )
            session.add(default_project)
            session.commit()

        # Get all users
        users = session.exec(select(User)).all()

        if not users:
            print("No users found.")
            return

        print(f"Found {len(users)} users to check.")
        added_count = 0

        for user in users:
            # Check if user is already a member of default project
            existing_member = session.exec(
                select(ProjectMember)
                .where(ProjectMember.project_id == DEFAULT_PROJECT_ID)
                .where(ProjectMember.user_id == user.id)
            ).first()

            if not existing_member:
                role = "admin" if user.is_superuser else "viewer"
                member = ProjectMember(project_id=DEFAULT_PROJECT_ID, user_id=user.id, role=role)
                session.add(member)
                print(f"  + Added '{user.email}' to Default Project as {role}")
                added_count += 1
            else:
                print(f"  - '{user.email}' already a member of Default Project")

        session.commit()
        print(f"Migration complete: Added {added_count} users to Default Project.")


def main():
    parser = argparse.ArgumentParser(description="Create an admin user for the test automation platform")
    parser.add_argument("--email", required=False, help="Admin user email address")
    parser.add_argument("--password", required=False, help="Admin user password")
    parser.add_argument("--name", default=None, help="Optional full name for the admin user")
    parser.add_argument(
        "--migrate", action="store_true", help="Also migrate existing projects to be owned by the admin"
    )
    parser.add_argument("--force-password", action="store_true", help="Update password if user already exists")
    parser.add_argument(
        "--add-all-to-default",
        action="store_true",
        help="Add all existing users to the Default Project (one-time migration)",
    )

    args = parser.parse_args()

    print("Initializing database...")
    init_db()

    # Handle --add-all-to-default option (standalone operation)
    if args.add_all_to_default:
        print("\nAdding all users to Default Project...")
        add_all_users_to_default_project()
        if not args.email:
            print("\nDone!")
            return

    # Creating admin user requires email and password
    if args.email and args.password:
        print("\nCreating admin user...")
        admin = create_admin_user(args.email, args.password, args.name, args.force_password)

        if args.migrate:
            print("\nMigrating existing data...")
            migrate_existing_data(admin)
    elif args.email or args.password:
        print("Error: Both --email and --password are required to create an admin user.")
        sys.exit(1)
    elif not args.add_all_to_default:
        print("Error: Either provide --email and --password or use --add-all-to-default")
        parser.print_help()
        sys.exit(1)

    print("\nDone!")
    print("\nNext steps:")
    print("1. Set REQUIRE_AUTH=false in .env to allow gradual migration")
    print("2. Users can register and be added to projects")
    print("3. When ready, set REQUIRE_AUTH=true to enforce authentication")


if __name__ == "__main__":
    main()
