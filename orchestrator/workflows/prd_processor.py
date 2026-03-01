"""
PRD Processor Workflow - Converts PDF PRDs to structured features and chunks
"""

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

import logging

from orchestrator.utils.string_utils import slugify

logger = logging.getLogger(__name__)


@dataclass
class Feature:
    name: str
    slug: str
    content: str
    requirements: list[str] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)  # Track consolidated sub-features
    category: str | None = None  # Optional category grouping


@dataclass
class PRDProcessorConfig:
    """Configuration for PRD processing behavior."""

    # Feature extraction
    target_feature_count: int = 15  # Aim for this many features
    max_feature_count: int = 25  # Trigger re-consolidation if exceeded
    min_requirements_per_feature: int = 1  # Filter features with fewer requirements

    # Chunk sizes (in characters, ~4 chars = 1 token)
    extraction_chunk_size: int = 40000  # chars for LLM extraction
    storage_chunk_size: int = 6000  # chars (~1500 tokens) for vector store
    overlap_size: int = 2000  # chars overlap between chunks

    # Semantic matching
    semantic_similarity_threshold: float = 0.3
    use_semantic_enrichment: bool = True

    # Context features
    include_context_features: bool = False


@dataclass
class Chunk:
    id: str
    content: str
    metadata: dict[str, Any]


class PRDProcessor:
    # Base directory (project root, two levels up from this file)
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

    def __init__(self, prds_dir: str = None, config: PRDProcessorConfig = None):
        # Use absolute path to project root's prds/ directory
        if prds_dir:
            self.prds_dir = Path(prds_dir)
        else:
            self.prds_dir = self.BASE_DIR / "prds"
        self.prds_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir = self.prds_dir / "uploads"
        self.uploads_dir.mkdir(exist_ok=True)

        # Use provided config or defaults
        self.config = config or PRDProcessorConfig()

    def process_prd(
        self, pdf_path: str, project_name: str | None = None, target_feature_count: int | None = None
    ) -> dict[str, Any]:
        """
        Main entry point - process a PDF PRD file.

        Args:
            pdf_path: Path to PDF file
            project_name: Optional name for the PRD project
            target_feature_count: Optional target number of features (overrides config)

        Returns:
            Dict with processing results
        """
        # Override config if target_feature_count provided
        if target_feature_count is not None:
            self.config.target_feature_count = target_feature_count

        pdf = Path(pdf_path)
        if not pdf.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Create project directory
        project_name = project_name or pdf.stem.replace(" ", "-").lower()
        project_dir = self.prds_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Copy original PDF (skip if already there)
        dest_pdf = project_dir / "original.pdf"
        if pdf.resolve() != dest_pdf.resolve():
            shutil.copy(pdf, dest_pdf)

        # 1. Parse PDF with MinerU
        logger.info(f"Parsing PDF: {pdf.name}...")
        markdown_path = self._parse_pdf(pdf, project_dir / "parsed")

        # Read markdown content for enrichment
        markdown_content = markdown_path.read_text()

        # 2. Extract Features using LLM
        logger.info(f"Extracting features with LLM (target: {self.config.target_feature_count})...")
        features = self._extract_features_with_llm(markdown_path)

        # 3. Enrich features with full content (semantic or keyword-based)
        logger.info(f"Enriching {len(features)} features with document content...")
        features = self._enrich_features_with_full_content(
            features, markdown_content, include_context_features=self.config.include_context_features
        )

        # 4. Semantic Chunking
        logger.info(f"Chunking {len(features)} features...")
        chunks = self._chunk_features(features)

        # 5. Store in ChromaDB
        logger.info("Storing vectors...")
        self._store_chunks(chunks, project_name)

        # 6. Save final metadata with features
        metadata = {
            "project": project_name,
            "features": [f.__dict__ for f in features],
            "total_chunks": len(chunks),
            "processed_at": datetime.now().isoformat(),
            "config": {
                "target_feature_count": self.config.target_feature_count,
                "use_semantic_enrichment": self.config.use_semantic_enrichment,
            },
        }
        (project_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        logger.info(f"Successfully processed PRD: {project_name} ({len(features)} features)")
        return metadata

    def _parse_pdf(self, pdf_path: Path, output_dir: Path) -> Path:
        """
        Convert PDF to markdown using pdfplumber (no GPU required).
        Falls back gracefully if PDF structure is complex.
        """
        output_dir.mkdir(exist_ok=True)

        # Check if already parsed
        target_md = output_dir / "content.md"
        if target_md.exists() and target_md.stat().st_size > 100:
            logger.info("PDF already parsed, reusing existing markdown.")
            return target_md

        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError(
                "pdfplumber not installed. PDF parsing requires pdfplumber. "
                "Please ensure pdfplumber>=0.10.0 is in requirements.txt."
            )

        logger.info("Extracting text from PDF using pdfplumber...")

        markdown_content = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Processing {total_pages} pages...")

                for i, page in enumerate(pdf.pages):
                    page_num = i + 1

                    # Extract text
                    text = page.extract_text() or ""

                    if text.strip():
                        # Add page separator for long documents
                        if page_num > 1:
                            markdown_content.append("\n\n---\n\n")

                        # Try to detect headings (lines that are short and possibly bold/larger)
                        lines = text.split("\n")
                        processed_lines = []

                        for line in lines:
                            line = line.strip()
                            if not line:
                                processed_lines.append("")
                                continue

                            # Heuristic: Short lines that look like headings
                            # (all caps, ends with colon, or is a numbered section)
                            if len(line) < 80 and (
                                line.isupper()
                                or line.endswith(":")
                                or re.match(r"^\d+\.?\s+\w", line)
                                or re.match(r"^[A-Z][A-Za-z\s]+$", line)
                            ):
                                # Treat as heading
                                processed_lines.append(f"\n## {line}\n")
                            else:
                                processed_lines.append(line)

                        markdown_content.append("\n".join(processed_lines))

                    # Progress indicator
                    if page_num % 10 == 0:
                        logger.info(f"  Processed {page_num}/{total_pages} pages...")

            # Combine all content
            full_content = "\n".join(markdown_content)

            if not full_content.strip():
                raise RuntimeError("PDF appears to be empty or image-only (no extractable text)")

            # Save to markdown file
            target_md.write_text(full_content, encoding="utf-8")
            logger.info(f"Successfully extracted {len(full_content)} characters from PDF")

            return target_md

        except Exception as e:
            raise RuntimeError(f"Failed to parse PDF: {str(e)}")

    def _extract_features_with_llm(self, markdown_path: Path) -> list[Feature]:
        """
        Use OpenAI (Map-Reduce) to intelligently extract features from potentially large PRD content.

        Strategy:
        1. Split content into large chunks (Map).
        2. Extract features from each chunk.
        3. Consolidate and deduplicate all features into a final list (Reduce).
        """
        import os

        from openai import OpenAI

        content = markdown_path.read_text()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not found. Returning empty features.")
            return []

        client = OpenAI(api_key=api_key)

        # 1. Split content into logical chunks (approx 12k tokens / 50k chars to be safe)
        # using our existing split helper but with larger size for LLM context
        chunk_size_chars = 40000

        chunks = []
        if len(content) <= chunk_size_chars:
            chunks.append(content)
        else:
            chunks = self._split_with_overlap(
                content, max_tokens=10000, overlap_tokens=500
            )  # helper uses 1 tok ~ 4 chars

        logger.info(f"Split PRD into {len(chunks)} chunks for processing.")

        all_raw_features = []

        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 2. Map Phase: Extract from each chunk logic parallelized
        logger.info(f"Starting parallel processing of {len(chunks)} chunks...")

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(self._extract_chunk_features, client, chunk): i for i, chunk in enumerate(chunks)
            }

            for future in as_completed(future_to_index):
                i = future_to_index[future]
                try:
                    chunk_features = future.result()
                    if chunk_features:
                        all_raw_features.extend(chunk_features)
                        logger.info(f"Chunk {i + 1} processed successfully ({len(chunk_features)} features).")
                    else:
                        logger.info(f"Chunk {i + 1} returned no features.")
                except Exception as e:
                    logger.error(f"Error extracting from chunk {i + 1}: {e}")

        logger.info(f"Collected {len(all_raw_features)} raw feature candidates.")

        # 3. Reduce Phase: Merge and Deduplicate
        if not all_raw_features:
            return []

        final_features_data = self._merge_features(client, all_raw_features)

        # Validate and re-consolidate if too many features
        if len(final_features_data) > self.config.max_feature_count:
            logger.warning(
                f"{len(final_features_data)} features exceeds max ({self.config.max_feature_count}), running additional consolidation..."
            )
            final_features_data = self._merge_features(client, final_features_data)

        # Convert to Feature objects
        features = []
        for f in final_features_data:
            name = f.get("name", "Unknown")
            features.append(
                Feature(
                    name=name,
                    slug=slugify(name),
                    content=f.get("description", ""),
                    requirements=f.get("requirements", []),
                    merged_from=f.get("merged_from", []),  # Track consolidated sub-features
                )
            )

        logger.info(f"Final consolidated feature count: {len(features)}")

        # Note: Enrichment is now done in process_prd() after this method returns
        return features

    def _extract_chunk_features(self, client, text: str) -> list[dict[str, Any]]:
        """Map step: Extract features from a single text chunk."""
        target = self.config.target_feature_count
        prompt = f"""Analyze this section of a PRD and extract HIGH-LEVEL TESTABLE FEATURES.

IMPORTANT GUIDELINES:
- Extract FEATURES, not individual requirements or user stories
- A feature is a MAJOR FUNCTIONAL AREA (e.g., "User Authentication", "Shopping Cart", "AI Assistant")
- Group related functionality under ONE feature:
  * All login/logout/password reset → "User Authentication"
  * All section editing/deletion/reorder → "Section Management"
  * All AI V1/V2/generation → "AI Assistant"
- Aim for {target} features total for the ENTIRE PRD (this chunk may have fewer)
- Requirements are the DETAILS within a feature, not separate features themselves

BAD examples (too granular):
- "Section Click Handler" - too specific
- "AI Assistant V1" - version shouldn't be a separate feature
- "Login Button" - UI element, not a feature

GOOD examples (high-level):
- "Section Management" - groups all section operations
- "AI Assistant" - groups all AI functionality
- "User Authentication" - groups all auth flows

CONTENT:
---
{text}
---

Return a JSON array where each object has:
- "name": High-level feature name (e.g., "Content Library", not "Library Save Button")
- "description": What this feature area does (1-2 sentences)
- "requirements": List of specific testable requirements within this feature

Ignore generic intro text. Focus on functional requirements.
Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-5.2", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )

        try:
            result = response.choices[0].message.content
            data = json.loads(result)
            # Handle if wrapped in a key like "features"
            if isinstance(data, dict):
                for key in ["features", "items", "data"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # If just a dict but not a list, maybe it's a single item or unknown structure?
                # Fallback: check if the dict acts like a single feature
                if "name" in data:
                    return [data]
                return []
            elif isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.error(f"Chunk parsing error: {e}")
            return []

    def _merge_features(self, client, raw_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reduce step: Consolidate duplicate features from multiple chunks."""

        # Serialize inputs to JSON for the LLM
        features_json = json.dumps(raw_features, indent=1)
        target = self.config.target_feature_count

        prompt = f"""You are a Product Manager consolidating features from a PRD.

TASK: Merge and consolidate {len(raw_features)} extracted features into approximately {target} high-level features.

RULES FOR HIERARCHICAL MERGING:
1. **Merge related features** by functional area:
   - "AI Assistant V1" + "AI Assistant V2" + "AI Description Generation" → "AI Assistant"
   - "Section Editing" + "Section Deletion" + "Section Reorder" + "Section Click" → "Section Management"
   - "Library Save" + "Library Templates" + "Library Search" + "Library Panel" → "Content Library"
   - "Itinerary List" + "Itinerary Search" + "Itinerary Filters" → "Itinerary Management"
   - "Book Now Button" + "Connect Trip" + "Trip Connection" → "Booking Integration"

2. **Combine requirements**: Merge all requirement lists from consolidated features (deduplicate similar ones)

3. **Track merged sources**: For each output feature, list which input features were merged into it

4. **Target count**: Aim for approximately {target} features (±5 is acceptable)

5. **Naming conventions**:
   - Use concise, professional names
   - Remove version numbers (V1, V2)
   - Remove UI element references (Button, Panel, Modal)
   - Use noun phrases: "Section Management", not "Managing Sections"

RAW INPUT ({len(raw_features)} features):
---
{features_json}
---

Return JSON: {{ "features": [...] }}
Each feature must have:
- "name": string (high-level feature name)
- "description": string (1-2 sentence summary)
- "requirements": [string] (all consolidated requirements)
- "merged_from": [string] (list of original feature names that were merged, empty if not merged)"""

        # Log before making the merge API call
        logger.info(f"Merging {len(raw_features)} features with LLM (prompt size: {len(features_json)} chars)...")

        response = client.chat.completions.create(
            model="gpt-5.2", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )

        try:
            result = response.choices[0].message.content
            data = json.loads(result)
            final_features = data.get("features", [])

            # Log after merge completes successfully
            logger.info(f"Merge completed successfully. Returning {len(final_features)} consolidated features.")

            return final_features
        except Exception as e:
            logger.error(f"Merge step error: {e}")
            return raw_features  # Fallback to raw list if merge fails

    def _get_embeddings(self, client, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts using OpenAI."""
        # Batch in groups of 100 to avoid API limits
        all_embeddings = []
        batch_size = 100

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Truncate very long texts to avoid token limits
            batch = [t[:8000] for t in batch]

            response = client.embeddings.create(model="text-embedding-3-small", input=batch)
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import numpy as np

        a_arr, b_arr = np.array(a), np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))

    def _enrich_features_with_full_content(
        self, features: list[Feature], full_markdown: str, include_context_features: bool = False
    ) -> list[Feature]:
        """
        Match document chunks to features using semantic similarity or keyword matching.

        Args:
            features: List of extracted features
            full_markdown: Full markdown content of the PRD
            include_context_features: Whether to add "Full Document Context" features
        """
        logger.info("Enriching features with full document content...")

        # Split entire document into overlapping chunks
        all_chunks_text = self._split_with_overlap(full_markdown, max_tokens=1500, overlap_tokens=200)
        logger.info(f"Created {len(all_chunks_text)} chunks from full document ({len(full_markdown)} chars)")

        feature_content_map = {f.slug: [] for f in features}
        unassigned_chunks = []

        # Use semantic matching if enabled and OpenAI key available
        if self.config.use_semantic_enrichment and os.getenv("OPENAI_API_KEY"):
            logger.info("Using semantic similarity for content-to-feature matching...")
            try:
                from openai import OpenAI

                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

                # Get embeddings for feature names + descriptions
                feature_texts = [f"{f.name}: {f.content[:500]}" for f in features]
                logger.info(f"Computing embeddings for {len(features)} features...")
                feature_embeddings = self._get_embeddings(client, feature_texts)

                # Get embeddings for chunks
                logger.info(f"Computing embeddings for {len(all_chunks_text)} chunks...")
                chunk_embeddings = self._get_embeddings(client, all_chunks_text)

                # Assign each chunk to most similar feature
                threshold = self.config.semantic_similarity_threshold
                for i, chunk_text in enumerate(all_chunks_text):
                    similarities = [self._cosine_similarity(chunk_embeddings[i], fe) for fe in feature_embeddings]
                    best_idx = max(range(len(similarities)), key=lambda x: similarities[x])
                    best_score = similarities[best_idx]

                    if best_score >= threshold:
                        feature_content_map[features[best_idx].slug].append(chunk_text)
                    else:
                        unassigned_chunks.append(chunk_text)

                logger.info(f"Semantic matching complete. Unassigned chunks: {len(unassigned_chunks)}")

            except Exception as e:
                logger.warning(f"Semantic matching failed, falling back to keyword matching: {e}")
                # Fall back to keyword matching
                feature_content_map, unassigned_chunks = self._keyword_match_chunks(features, all_chunks_text)
        else:
            logger.info("Using keyword matching for content-to-feature matching...")
            feature_content_map, unassigned_chunks = self._keyword_match_chunks(features, all_chunks_text)

        # Update features with their matched content
        enriched_features = []
        for feature in features:
            matched_chunks = feature_content_map[feature.slug]
            if matched_chunks:
                # Combine matched chunks
                full_content = "\n\n---\n\n".join(matched_chunks)
                enriched_features.append(
                    Feature(
                        name=feature.name,
                        slug=feature.slug,
                        content=full_content,
                        requirements=feature.requirements,
                        merged_from=feature.merged_from,
                    )
                )
            else:
                # Keep original LLM description if no matches
                enriched_features.append(feature)

        # Only add context features if explicitly requested
        if include_context_features:
            enriched_features.append(
                Feature(
                    name="Full Document Context", slug="full-document", content=full_markdown[:50000], requirements=[]
                )
            )

            if unassigned_chunks:
                general_content = "\n\n---\n\n".join(unassigned_chunks[:20])
                enriched_features.append(
                    Feature(
                        name="General PRD Context", slug="general-context", content=general_content, requirements=[]
                    )
                )

        logger.info(f"Enriched {len(enriched_features)} features with full document content")
        return enriched_features

    def _keyword_match_chunks(self, features: list[Feature], all_chunks_text: list[str]) -> tuple:
        """
        Fallback method: Match chunks to features using keyword matching.

        Returns:
            Tuple of (feature_content_map, unassigned_chunks)
        """
        feature_content_map = {f.slug: [] for f in features}
        unassigned_chunks = []

        for chunk_text in all_chunks_text:
            chunk_lower = chunk_text.lower()
            assigned = False

            # Try to match chunk to a feature by name presence
            for feature in features:
                feature_words = feature.name.lower().split()
                # Require full name match or at least 2 matching words
                if feature.name.lower() in chunk_lower:
                    feature_content_map[feature.slug].append(chunk_text)
                    assigned = True
                    break
                elif len(feature_words) >= 2:
                    matches = sum(1 for w in feature_words if w in chunk_lower and len(w) > 3)
                    if matches >= 2:
                        feature_content_map[feature.slug].append(chunk_text)
                        assigned = True
                        break

            if not assigned:
                unassigned_chunks.append(chunk_text)

        return feature_content_map, unassigned_chunks

    def _chunk_features(self, features: list[Feature]) -> list[Chunk]:
        """
        Split features into searchable chunks with overlap.
        """
        chunks = []

        for feature in features:
            content = feature.content
            # Rough token estimate (4 chars per token)
            tokens = len(content) // 4

            if tokens <= 1500:
                chunks.append(
                    Chunk(
                        id=f"{feature.slug}-001",
                        content=content,
                        metadata={
                            "feature": feature.name,
                            "feature_slug": feature.slug,
                            "type": "full_feature",
                            "tokens": tokens,
                        },
                    )
                )
            else:
                sub_chunks = self._split_with_overlap(content, 1500, 200)
                for i, sub in enumerate(sub_chunks):
                    chunks.append(
                        Chunk(
                            id=f"{feature.slug}-{i + 1:03d}",
                            content=sub,
                            metadata={
                                "feature": feature.name,
                                "feature_slug": feature.slug,
                                "type": "partial",
                                "chunk_index": i,
                                "total_chunks": len(sub_chunks),
                            },
                        )
                    )
        return chunks

    def _split_with_overlap(self, text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
        """Simple character-based splitting (approximate)"""
        # Approx chars
        chunk_size = max_tokens * 4
        overlap_size = overlap_tokens * 4

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)

            # Adjust end to nearest newline if possible to avoid cutting words
            if end < text_len:
                last_newline = text.rfind("\n", start, end)
                if last_newline != -1 and last_newline > start + chunk_size // 2:
                    end = last_newline

            chunks.append(text[start:end])

            start = end - overlap_size
            if start < 0:
                start = 0  # should generally not happen unless chunk_size < overlap

            # Avoid infinite loop if no progress
            if start >= end:
                break

            if end == text_len:
                break

        return chunks

    def _store_chunks(self, chunks: list[Chunk], project_name: str):
        """
        Store chunks in ChromaDB.
        """
        # Import here to avoid circular dependencies if any
        try:
            from orchestrator.memory import get_memory_manager

            manager = get_memory_manager(project_id=project_name)

            for chunk in chunks:
                # Assuming add_prd_chunk exists in vector_store (we need to add it next)
                if hasattr(manager.vector_store, "add_prd_chunk"):
                    manager.vector_store.add_prd_chunk(
                        chunk_id=chunk.id, content=chunk.content, metadata=chunk.metadata
                    )
                else:
                    logger.warning("add_prd_chunk method not found in VectorStore")

            # Save metadata
            metadata = {
                "project": project_name,
                "total_chunks": len(chunks),
                "processed_at": datetime.now().isoformat(),
                # "features": [f.name for f in features] # passed features not avail here in scope, ignore for now
            }
            metadata_path = self.prds_dir / project_name / "metadata.json"

            # Update metadata if exists (to keep features list if added elsewhere)
            if metadata_path.exists():
                existing = json.loads(metadata_path.read_text())
                existing.update(metadata)
                metadata = existing

            metadata_path.write_text(json.dumps(metadata, indent=2))

        except ImportError:
            logger.warning("Memory system not available, skipping vector storage")


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument("--project", help="Project name")
    args = parser.parse_args()

    processor = PRDProcessor()
    processor.process_prd(args.pdf_path, args.project)
