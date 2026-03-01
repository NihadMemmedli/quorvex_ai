import csv
import io
import re


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames."""
    # Replace invalid chars with underscore
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    s = re.sub(r"[-\s]+", "_", s)
    return s


def parse_testrail_csv(content: bytes) -> list[dict[str, str]]:
    """
    Parse TestRail CSV content and return a list of test specs.
    Returns a list of dicts with keys: name, content.
    """
    # Read the header line first to handle duplicate columns
    text = content.decode("utf-8-sig")  # Handle BOM
    f = io.StringIO(text)
    reader_raw = csv.reader(f)
    try:
        headers = next(reader_raw)
    except StopIteration:
        return []

    # Deduplicate headers
    unique_headers = []
    seen = {}
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            unique_headers.append(h)

    # Use DictReader with unique headers
    reader = csv.DictReader(f, fieldnames=unique_headers)

    specs = []

    for row in reader:
        # Extract fields
        test_id = row.get("ID", "").strip()
        title = row.get("Title", "").strip()

        # Description parts
        description_parts = []
        if test_id:
            description_parts.append(f"ID: {test_id}")

        desc_text = row.get("Goals", "") or row.get("Mission", "") or ""
        if desc_text:
            description_parts.append(desc_text)

        preconditions = row.get("Preconditions", "")
        if preconditions:
            description_parts.append("Preconditions: " + preconditions)

        expected = row.get("Expected Result", "")
        if expected:
            description_parts.append("Expected Result: " + expected)

        description_combined = "\n".join(description_parts)

        # Steps
        # Check "Steps" and "Steps_1" (duplicate), and "Steps (Step)"
        steps_text = row.get("Steps", "")
        if not steps_text:
            # Try duplicate steps column
            steps_text = row.get("Steps_1", "")

        step_lines = []
        if steps_text:
            for line in steps_text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Check if it already has numbering
                if not re.match(r"^\d+\.", line):
                    # No numbering, so we will handle it when joining
                    step_lines.append(line)
                else:
                    # Has numbering
                    step_lines.append(line)

        # Granular steps "Steps (Step)"
        steps_step = row.get("Steps (Step)", "")
        if steps_step:
            step_lines.append(steps_step)
            steps_expected = row.get("Steps (Expected Result)", "")
            if steps_expected:
                step_lines.append(f"Expected: {steps_expected}")

        # Construct content
        # SpecBuilder format
        spec_content = f"# {title}\n\n"
        if description_combined:
            spec_content += f"{description_combined}\n\n"

        if step_lines:
            for i, step in enumerate(step_lines):
                # Ensure it starts with number dot
                if re.match(r"^\d+\.", step):
                    spec_content += f"{step}\n"
                else:
                    spec_content += f"{i + 1}. {step}\n"
        else:
            pass

        file_name = f"{sanitize_filename(title)}_{test_id.lower()}.md"

        specs.append({"name": file_name, "content": spec_content})

    return specs
