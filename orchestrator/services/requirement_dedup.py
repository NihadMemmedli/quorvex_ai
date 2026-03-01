"""
Requirement Deduplication Service

Provides methods for detecting and merging duplicate requirements using
both exact matching and semantic similarity via embeddings.
"""

import logging
import re
import string
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DuplicateMatch:
    """Represents a potential duplicate match."""

    requirement_id: int
    req_code: str
    title: str
    description: str | None
    acceptance_criteria: list[str]
    similarity: float


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate requirements."""

    canonical_id: int
    canonical_code: str
    canonical_title: str
    duplicates: list[DuplicateMatch]
    merged_criteria: list[str]


class RequirementDeduplicationService:
    """
    Service for detecting and merging duplicate requirements.

    Uses a hybrid approach:
    - Exact matching: Normalized title comparison
    - Semantic matching: Embedding-based similarity for near-duplicates
    """

    EXACT_MATCH_THRESHOLD = 1.0
    SEMANTIC_THRESHOLD = 0.85

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self._embedding_client = None

    def _get_embedding_client(self):
        """Lazy load embedding client."""
        if self._embedding_client is None:
            try:
                from memory.embeddings import get_embedding_client

                self._embedding_client = get_embedding_client()
            except Exception as e:
                logger.warning(f"Could not initialize embedding client: {e}")
                self._embedding_client = None
        return self._embedding_client

    def normalize_title(self, title: str) -> str:
        """
        Normalize a title for comparison.

        - Lowercase
        - Remove punctuation
        - Collapse whitespace
        - Strip leading/trailing whitespace

        Args:
            title: The title to normalize

        Returns:
            Normalized title string
        """
        if not title:
            return ""

        # Lowercase
        normalized = title.lower()

        # Remove punctuation
        normalized = normalized.translate(str.maketrans("", "", string.punctuation))

        # Collapse multiple whitespace to single space
        normalized = re.sub(r"\s+", " ", normalized)

        # Strip leading/trailing whitespace
        normalized = normalized.strip()

        return normalized

    def normalize_criterion(self, criterion: str) -> str:
        """
        Normalize an acceptance criterion for comparison.

        Args:
            criterion: The criterion to normalize

        Returns:
            Normalized criterion string
        """
        if not criterion:
            return ""

        # Same normalization as title
        normalized = criterion.lower()
        normalized = normalized.translate(str.maketrans("", "", string.punctuation))
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.strip()

        return normalized

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity (0.0 to 1.0)
        """
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def check_duplicate(
        self, title: str, description: str | None, existing_requirements: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, list[DuplicateMatch]]:
        """
        Check if a title/description matches existing requirements.

        Args:
            title: Title to check
            description: Description to check
            existing_requirements: List of existing requirements with keys:
                id, req_code, title, description, acceptance_criteria, title_embedding

        Returns:
            Tuple of (exact_match, near_matches)
            - exact_match: The matching requirement if exact match found, None otherwise
            - near_matches: List of DuplicateMatch objects for semantic matches
        """
        normalized_new = self.normalize_title(title)
        exact_match = None
        near_matches: list[DuplicateMatch] = []

        # Check for exact match first
        for req in existing_requirements:
            normalized_existing = self.normalize_title(req.get("title", ""))
            if normalized_new == normalized_existing:
                exact_match = req
                break

        if exact_match:
            return exact_match, []

        # If no exact match, try semantic matching
        embedding_client = self._get_embedding_client()
        if embedding_client is None:
            return None, []

        try:
            # Combine title and description for embedding
            new_text = title
            if description:
                new_text = f"{title}. {description}"

            new_embedding = embedding_client.embed(new_text)

            for req in existing_requirements:
                # Try to get cached embedding or compute new one
                existing_embedding = req.get("title_embedding")

                if existing_embedding is None:
                    # Compute embedding for existing requirement
                    existing_text = req.get("title", "")
                    if req.get("description"):
                        existing_text = f"{existing_text}. {req.get('description')}"
                    existing_embedding = embedding_client.embed(existing_text)

                similarity = self._cosine_similarity(new_embedding, existing_embedding)

                if similarity >= self.SEMANTIC_THRESHOLD:
                    near_matches.append(
                        DuplicateMatch(
                            requirement_id=req.get("id"),
                            req_code=req.get("req_code", ""),
                            title=req.get("title", ""),
                            description=req.get("description"),
                            acceptance_criteria=req.get("acceptance_criteria", []),
                            similarity=similarity,
                        )
                    )

            # Sort by similarity descending
            near_matches.sort(key=lambda x: x.similarity, reverse=True)

        except Exception as e:
            logger.warning(f"Error computing semantic similarity: {e}")

        return None, near_matches

    def find_duplicate_groups(
        self, requirements: list[dict[str, Any]], threshold: float = None
    ) -> list[DuplicateGroup]:
        """
        Find groups of duplicate requirements using semantic similarity.

        Args:
            requirements: List of requirements to analyze
            threshold: Similarity threshold (defaults to SEMANTIC_THRESHOLD)

        Returns:
            List of DuplicateGroup objects
        """
        if threshold is None:
            threshold = self.SEMANTIC_THRESHOLD

        if not requirements:
            return []

        embedding_client = self._get_embedding_client()
        if embedding_client is None:
            # Fall back to exact matching only
            return self._find_exact_duplicate_groups(requirements)

        # Compute embeddings for all requirements
        embeddings = []
        try:
            texts = []
            for req in requirements:
                text = req.get("title", "")
                if req.get("description"):
                    text = f"{text}. {req.get('description')}"
                texts.append(text)

            embeddings = embedding_client.embed_batch(texts)
        except Exception as e:
            logger.warning(f"Error computing batch embeddings: {e}")
            return self._find_exact_duplicate_groups(requirements)

        # Build similarity matrix and find groups
        n = len(requirements)
        used = set()
        groups: list[DuplicateGroup] = []

        for i in range(n):
            if i in used:
                continue

            # Find all requirements similar to this one
            similar_indices = []
            for j in range(i + 1, n):
                if j in used:
                    continue

                similarity = self._cosine_similarity(embeddings[i], embeddings[j])
                if similarity >= threshold:
                    similar_indices.append((j, similarity))

            if similar_indices:
                # This requirement has duplicates
                # The canonical is the one with the most acceptance criteria
                # or the first one if tied
                candidates = [(i, 1.0)] + similar_indices

                # Find best canonical (most acceptance criteria)
                best_idx = i
                best_criteria_count = len(requirements[i].get("acceptance_criteria", []))

                for idx, _ in candidates:
                    count = len(requirements[idx].get("acceptance_criteria", []))
                    if count > best_criteria_count:
                        best_criteria_count = count
                        best_idx = idx

                # Build duplicate list (excluding canonical)
                duplicates = []
                all_criteria = list(requirements[best_idx].get("acceptance_criteria", []))

                for idx, sim in candidates:
                    if idx == best_idx:
                        continue

                    req = requirements[idx]
                    duplicates.append(
                        DuplicateMatch(
                            requirement_id=req.get("id"),
                            req_code=req.get("req_code", ""),
                            title=req.get("title", ""),
                            description=req.get("description"),
                            acceptance_criteria=req.get("acceptance_criteria", []),
                            similarity=sim
                            if idx != i
                            else self._cosine_similarity(embeddings[best_idx], embeddings[i]),
                        )
                    )

                    # Collect criteria for merging
                    all_criteria.extend(req.get("acceptance_criteria", []))
                    used.add(idx)

                # Mark canonical as used
                used.add(best_idx)

                # Merge criteria
                merged_criteria = self.merge_acceptance_criteria_from_list(all_criteria)

                canonical = requirements[best_idx]
                groups.append(
                    DuplicateGroup(
                        canonical_id=canonical.get("id"),
                        canonical_code=canonical.get("req_code", ""),
                        canonical_title=canonical.get("title", ""),
                        duplicates=duplicates,
                        merged_criteria=merged_criteria,
                    )
                )

        return groups

    def _find_exact_duplicate_groups(self, requirements: list[dict[str, Any]]) -> list[DuplicateGroup]:
        """
        Find duplicate groups using exact title matching only.
        Fallback when embeddings are not available.

        Args:
            requirements: List of requirements to analyze

        Returns:
            List of DuplicateGroup objects
        """
        # Group by normalized title
        title_groups: dict[str, list[dict[str, Any]]] = {}

        for req in requirements:
            normalized = self.normalize_title(req.get("title", ""))
            if normalized not in title_groups:
                title_groups[normalized] = []
            title_groups[normalized].append(req)

        groups: list[DuplicateGroup] = []

        for _normalized_title, reqs in title_groups.items():
            if len(reqs) <= 1:
                continue

            # Find best canonical (most acceptance criteria)
            best_req = max(reqs, key=lambda r: len(r.get("acceptance_criteria", [])))

            duplicates = []
            all_criteria = list(best_req.get("acceptance_criteria", []))

            for req in reqs:
                if req.get("id") == best_req.get("id"):
                    continue

                duplicates.append(
                    DuplicateMatch(
                        requirement_id=req.get("id"),
                        req_code=req.get("req_code", ""),
                        title=req.get("title", ""),
                        description=req.get("description"),
                        acceptance_criteria=req.get("acceptance_criteria", []),
                        similarity=1.0,  # Exact match
                    )
                )

                all_criteria.extend(req.get("acceptance_criteria", []))

            merged_criteria = self.merge_acceptance_criteria_from_list(all_criteria)

            groups.append(
                DuplicateGroup(
                    canonical_id=best_req.get("id"),
                    canonical_code=best_req.get("req_code", ""),
                    canonical_title=best_req.get("title", ""),
                    duplicates=duplicates,
                    merged_criteria=merged_criteria,
                )
            )

        return groups

    def merge_acceptance_criteria(self, requirements: list[dict[str, Any]]) -> list[str]:
        """
        Merge acceptance criteria from multiple requirements.

        - Collects all criteria
        - Normalizes for comparison
        - Deduplicates by normalized text
        - Returns unique criteria (original text preserved)

        Args:
            requirements: List of requirements with acceptance_criteria field

        Returns:
            List of unique acceptance criteria
        """
        all_criteria = []
        for req in requirements:
            all_criteria.extend(req.get("acceptance_criteria", []))

        return self.merge_acceptance_criteria_from_list(all_criteria)

    def merge_acceptance_criteria_from_list(self, criteria: list[str]) -> list[str]:
        """
        Merge and deduplicate a list of acceptance criteria.

        Args:
            criteria: List of acceptance criteria strings

        Returns:
            List of unique acceptance criteria
        """
        seen_normalized = set()
        unique_criteria = []

        for criterion in criteria:
            if not criterion or not criterion.strip():
                continue

            normalized = self.normalize_criterion(criterion)

            if normalized and normalized not in seen_normalized:
                seen_normalized.add(normalized)
                unique_criteria.append(criterion.strip())

        return unique_criteria

    def get_recommendation(self, exact_match: dict[str, Any] | None, near_matches: list[DuplicateMatch]) -> str:
        """
        Get a recommendation based on duplicate check results.

        Args:
            exact_match: Exact match found, if any
            near_matches: List of semantic near-matches

        Returns:
            One of: "create", "update_existing", "review_matches"
        """
        if exact_match:
            return "update_existing"

        if near_matches and near_matches[0].similarity >= 0.95:
            return "update_existing"

        if near_matches:
            return "review_matches"

        return "create"


# Global service instance cache
_service_cache: dict[str, RequirementDeduplicationService] = {}


def get_deduplication_service(project_id: str = "default") -> RequirementDeduplicationService:
    """
    Get a deduplication service instance for a project.

    Args:
        project_id: Project ID

    Returns:
        RequirementDeduplicationService instance
    """
    global _service_cache

    if project_id not in _service_cache:
        _service_cache[project_id] = RequirementDeduplicationService(project_id)

    return _service_cache[project_id]
