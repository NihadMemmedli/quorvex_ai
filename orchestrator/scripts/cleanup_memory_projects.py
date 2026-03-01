import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add orchestrator to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from memory.config import get_config
from memory.vector_store import VectorStore


def cleanup_projects():
    """
    Consolidate duplicate projects (e.g. example.com, example-app) into the canonical one (example.com).
    """
    print("🧹 Starting Project Memory Cleanup...")

    # Use the same path definition as config.py
    config_persist_dir = project_root.parent / "data" / "chromadb"
    if not config_persist_dir.exists():
        print(f"❌ Persist directory not found: {config_persist_dir}")
        return

    vector_store = VectorStore(persist_directory=str(config_persist_dir))
    config = get_config()
    prefix = config.collection_prefix

    # Define mapping: old_project_id -> new_project_id
    migrations = {
        "old-project-name": "example.com",
        "old-app": "example.com",
        # "example.com" # Target is destination
    }

    # Collections to migrate
    collections = [
        VectorStore.COLLECTION_TEST_PATTERNS,
        VectorStore.COLLECTION_APPLICATION_ELEMENTS,
        VectorStore.COLLECTION_TEST_IDEAS,
    ]

    for old_id, new_id in migrations.items():
        if old_id == new_id:
            continue

        print(f"\n🔄 Migrating {old_id} -> {new_id}")

        for base_name in collections:
            # Construct actual collection names using prefix
            # Format: {prefix}_{project_id}_{base_name}
            old_col_name = f"{prefix}_{old_id}_{base_name}"
            target_col_name = f"{prefix}_{new_id}_{base_name}"

            try:
                # 1. Get from OLD
                try:
                    old_col = vector_store.client.get_collection(name=old_col_name)
                except Exception:
                    print(f"   Skipping {old_col_name} (not found)")
                    continue

                data = old_col.get()
                if not data["ids"]:
                    print(f"   {old_col_name} is empty.")
                    # cleanup even if empty?
                    vector_store.client.delete_collection(name=old_col_name)
                    continue

                print(f"   Found {len(data['ids'])} items in {old_col_name}")

                # 2. Add to NEW
                # We need to get/create target collection manually to ensure it uses the new naming
                # The VectorStore usually prefixes with configured project_id.
                # Here we are bypassing the wrapper slightly to manage names directly.

                try:
                    target_col = vector_store.client.get_collection(name=target_col_name)
                except Exception:
                    target_col = vector_store.client.create_collection(
                        name=target_col_name,
                        metadata={"hnsw:space": "cosine"},
                        # We skip embedding function here assuming embeddings are pre-calculated?
                        # Wait, chroma collections store embeddings or compute them?
                        # If we just copy documents/metadatas/embeddings, we don't need the function.
                    )

                # Copy data
                # We should use batches if data is large, but likely small for now.
                target_col.add(
                    ids=data["ids"],
                    embeddings=data["embeddings"],
                    metadatas=data["metadatas"],
                    documents=data["documents"],
                )
                print(f"   ✅ Moved {len(data['ids'])} items to {target_col_name}")

                # 3. Delete OLD
                vector_store.client.delete_collection(name=old_col_name)
                print(f"   🗑️  Deleted old collection {old_col_name}")

            except Exception as e:
                print(f"   ❌ Error migrating {base_name}: {e}")

    print("\n✨ Migration Complete!")

    # --- Part 2: Delete Empty/Unwanted Projects ---
    projects_to_delete = ["default", "herokuapp", "localhost", "test_patterns"]
    print(f"\n🗑️  Deleting unused projects: {projects_to_delete}")

    for proj in projects_to_delete:
        for base_name in collections:
            col_name = f"{prefix}_{proj}_{base_name}"
            try:
                vector_store.client.delete_collection(name=col_name)
                print(f"   Removed {col_name}")
            except Exception:
                pass  # Already gone

    # --- Part 2b: Delete "Root" Collections (no project ID) ---
    # These appear as project "test_patterns" in the UI because of parsing logic
    print("\n🗑️  Deleting root (no-project) collections...")
    for base_name in collections:
        col_name = f"{prefix}_{base_name}"
        try:
            vector_store.client.delete_collection(name=col_name)
            print(f"   Removed {col_name}")
        except Exception:
            pass

    # --- Part 3: Deep Clean Messy Data in active project ---
    target_project = "example.com"
    print(f"\ndataset Deep Cleaning {target_project}...")

    # We primarily care about test_patterns where the messy action descriptions are
    messy_col_name = f"{prefix}_{target_project}_{VectorStore.COLLECTION_TEST_PATTERNS}"
    try:
        col = vector_store.client.get_collection(name=messy_col_name)
        data = col.get()

        ids_to_delete = []
        if data["ids"]:
            for i, doc_id in enumerate(data["ids"]):
                # Check document content (description)
                doc_text = data["documents"][i] if data["documents"] else ""

                # Check metadata target
                meta = data["metadatas"][i] if data["metadatas"] else {}
                target = meta.get("target", "")

                is_messy = False

                # Condition 1: "WARNING Notifications..."
                if "WARNING" in doc_text and "Notifications permission" in doc_text:
                    is_messy = True

                # Condition 2: "Page state" dump
                if "Page state" in doc_text or "Page state" in target:
                    is_messy = True

                # Condition 3: Excessively long description/target
                if len(doc_text) > 500 or len(target) > 500:
                    is_messy = True

                if is_messy:
                    ids_to_delete.append(doc_id)
                    print(f"   Found messy item: {doc_id} ({len(doc_text)} chars)")

        if ids_to_delete:
            col.delete(ids=ids_to_delete)
            print(f"   ✅ Deleted {len(ids_to_delete)} messy items from {target_project}")
        else:
            print(f"   No messy items found in {target_project}")

    except Exception as e:
        print(f"   Error scanning {target_project}: {e}")

    print("\n✨ All Cleanup Tasks Complete!")


if __name__ == "__main__":
    cleanup_projects()
