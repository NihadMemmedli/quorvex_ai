"""
Tests for Requirement Deduplication Service

Tests the functionality of:
- normalize_title()
- check_duplicate()
- merge_acceptance_criteria()
- find_duplicate_groups()
"""

import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.requirement_dedup import DuplicateMatch, RequirementDeduplicationService, get_deduplication_service


class TestNormalizeTitle:
    """Tests for normalize_title() method."""

    def test_lowercase(self):
        """Should convert to lowercase."""
        service = RequirementDeduplicationService()
        assert service.normalize_title("User Authentication") == "user authentication"

    def test_remove_punctuation(self):
        """Should remove punctuation marks."""
        service = RequirementDeduplicationService()
        assert service.normalize_title("User's Login!") == "users login"
        assert service.normalize_title("Hello, World.") == "hello world"

    def test_collapse_whitespace(self):
        """Should collapse multiple spaces to single space."""
        service = RequirementDeduplicationService()
        assert service.normalize_title("User    Authentication") == "user authentication"
        assert service.normalize_title("  Login   Flow  ") == "login flow"

    def test_strip_whitespace(self):
        """Should strip leading and trailing whitespace."""
        service = RequirementDeduplicationService()
        assert service.normalize_title("  User Login  ") == "user login"

    def test_empty_string(self):
        """Should handle empty strings."""
        service = RequirementDeduplicationService()
        assert service.normalize_title("") == ""
        assert service.normalize_title(None) == ""

    def test_combined_transformations(self):
        """Should apply all transformations together."""
        service = RequirementDeduplicationService()
        # Title with mixed case, punctuation, and extra whitespace
        assert service.normalize_title("  User's  Login-Flow!  ") == "users loginflow"


class TestNormalizeCriterion:
    """Tests for normalize_criterion() method."""

    def test_basic_normalization(self):
        """Should normalize acceptance criterion text."""
        service = RequirementDeduplicationService()
        assert service.normalize_criterion("User should be able to log in.") == "user should be able to log in"

    def test_empty_criterion(self):
        """Should handle empty strings."""
        service = RequirementDeduplicationService()
        assert service.normalize_criterion("") == ""
        assert service.normalize_criterion(None) == ""


class TestMergeAcceptanceCriteria:
    """Tests for merge_acceptance_criteria() method."""

    def test_merge_unique_criteria(self):
        """Should preserve all unique criteria."""
        service = RequirementDeduplicationService()
        requirements = [
            {"acceptance_criteria": ["Criterion A", "Criterion B"]},
            {"acceptance_criteria": ["Criterion C", "Criterion D"]},
        ]
        merged = service.merge_acceptance_criteria(requirements)
        assert len(merged) == 4
        assert "Criterion A" in merged
        assert "Criterion B" in merged
        assert "Criterion C" in merged
        assert "Criterion D" in merged

    def test_deduplicate_exact_matches(self):
        """Should remove exact duplicate criteria."""
        service = RequirementDeduplicationService()
        requirements = [
            {"acceptance_criteria": ["User can log in", "User can log out"]},
            {"acceptance_criteria": ["User can log in", "User can reset password"]},
        ]
        merged = service.merge_acceptance_criteria(requirements)
        assert len(merged) == 3
        # "User can log in" should appear only once

    def test_deduplicate_normalized_matches(self):
        """Should remove criteria that match after normalization."""
        service = RequirementDeduplicationService()
        requirements = [
            {"acceptance_criteria": ["User can log in."]},
            {"acceptance_criteria": ["user can log in"]},  # Same after normalization
        ]
        merged = service.merge_acceptance_criteria(requirements)
        assert len(merged) == 1

    def test_skip_empty_criteria(self):
        """Should skip empty or whitespace-only criteria."""
        service = RequirementDeduplicationService()
        requirements = [{"acceptance_criteria": ["Valid criterion", "", "  ", "Another valid"]}]
        merged = service.merge_acceptance_criteria(requirements)
        assert len(merged) == 2
        assert "Valid criterion" in merged
        assert "Another valid" in merged

    def test_empty_requirements_list(self):
        """Should handle empty requirements list."""
        service = RequirementDeduplicationService()
        merged = service.merge_acceptance_criteria([])
        assert merged == []

    def test_requirements_without_criteria(self):
        """Should handle requirements missing acceptance_criteria field."""
        service = RequirementDeduplicationService()
        requirements = [{}, {"acceptance_criteria": ["Criterion A"]}]
        merged = service.merge_acceptance_criteria(requirements)
        assert len(merged) == 1


class TestMergeAcceptanceCriteriaFromList:
    """Tests for merge_acceptance_criteria_from_list() method."""

    def test_basic_merge(self):
        """Should merge and deduplicate a list of criteria."""
        service = RequirementDeduplicationService()
        criteria = ["A", "B", "A", "C"]
        merged = service.merge_acceptance_criteria_from_list(criteria)
        assert len(merged) == 3

    def test_preserve_original_text(self):
        """Should preserve original text of first occurrence."""
        service = RequirementDeduplicationService()
        criteria = ["User can LOG IN", "user can log in"]
        merged = service.merge_acceptance_criteria_from_list(criteria)
        assert len(merged) == 1
        assert merged[0] == "User can LOG IN"  # First occurrence preserved


class TestCheckDuplicate:
    """Tests for check_duplicate() method."""

    def test_exact_match(self):
        """Should detect exact title matches."""
        service = RequirementDeduplicationService()
        existing = [
            {
                "id": 1,
                "req_code": "REQ-001",
                "title": "User Authentication",
                "description": "Users can log in",
                "acceptance_criteria": [],
            }
        ]

        exact_match, near_matches = service.check_duplicate("User Authentication", None, existing)

        assert exact_match is not None
        assert exact_match["id"] == 1
        assert len(near_matches) == 0

    def test_exact_match_with_normalization(self):
        """Should detect exact matches after normalization."""
        service = RequirementDeduplicationService()
        existing = [
            {
                "id": 1,
                "req_code": "REQ-001",
                "title": "User's Authentication!",
                "description": None,
                "acceptance_criteria": [],
            }
        ]

        exact_match, near_matches = service.check_duplicate("users authentication", None, existing)

        assert exact_match is not None
        assert exact_match["id"] == 1

    def test_no_match(self):
        """Should return None when no match found."""
        service = RequirementDeduplicationService()
        existing = [
            {
                "id": 1,
                "req_code": "REQ-001",
                "title": "User Authentication",
                "description": None,
                "acceptance_criteria": [],
            }
        ]

        exact_match, near_matches = service.check_duplicate("Password Reset", None, existing)

        assert exact_match is None
        # near_matches may be empty if embeddings not available


class TestFindDuplicateGroupsExact:
    """Tests for find_duplicate_groups() with exact matching fallback."""

    def test_find_exact_duplicate_groups(self):
        """Should find groups of exact duplicate titles."""
        service = RequirementDeduplicationService()

        # Mock embedding client to force exact matching fallback
        service._embedding_client = None

        requirements = [
            {"id": 1, "req_code": "REQ-001", "title": "User Login", "description": None, "acceptance_criteria": ["A"]},
            {"id": 2, "req_code": "REQ-002", "title": "User Login", "description": None, "acceptance_criteria": ["B"]},
            {
                "id": 3,
                "req_code": "REQ-003",
                "title": "Password Reset",
                "description": None,
                "acceptance_criteria": ["C"],
            },
        ]

        groups = service._find_exact_duplicate_groups(requirements)

        assert len(groups) == 1  # One group of duplicates
        assert groups[0].canonical_title == "User Login"
        assert len(groups[0].duplicates) == 1  # One duplicate (the other "User Login")

    def test_canonical_has_most_criteria(self):
        """Should choose requirement with most criteria as canonical."""
        service = RequirementDeduplicationService()

        requirements = [
            {"id": 1, "req_code": "REQ-001", "title": "User Login", "description": None, "acceptance_criteria": ["A"]},
            {
                "id": 2,
                "req_code": "REQ-002",
                "title": "User Login",
                "description": None,
                "acceptance_criteria": ["A", "B", "C"],
            },
        ]

        groups = service._find_exact_duplicate_groups(requirements)

        assert len(groups) == 1
        assert groups[0].canonical_id == 2  # Has more criteria

    def test_merge_criteria_in_group(self):
        """Should merge acceptance criteria when creating group."""
        service = RequirementDeduplicationService()

        requirements = [
            {
                "id": 1,
                "req_code": "REQ-001",
                "title": "User Login",
                "description": None,
                "acceptance_criteria": ["A", "B"],
            },
            {
                "id": 2,
                "req_code": "REQ-002",
                "title": "User Login",
                "description": None,
                "acceptance_criteria": ["B", "C"],
            },
        ]

        groups = service._find_exact_duplicate_groups(requirements)

        assert len(groups) == 1
        merged = groups[0].merged_criteria
        assert len(merged) == 3  # A, B, C (B deduplicated)


class TestGetRecommendation:
    """Tests for get_recommendation() method."""

    def test_exact_match_recommendation(self):
        """Should recommend update_existing for exact match."""
        service = RequirementDeduplicationService()
        recommendation = service.get_recommendation(
            {"id": 1},  # exact_match
            [],  # near_matches
        )
        assert recommendation == "update_existing"

    def test_high_similarity_recommendation(self):
        """Should recommend update_existing for very high similarity."""
        service = RequirementDeduplicationService()
        near_matches = [
            DuplicateMatch(
                requirement_id=1,
                req_code="REQ-001",
                title="Test",
                description=None,
                acceptance_criteria=[],
                similarity=0.96,
            )
        ]
        recommendation = service.get_recommendation(None, near_matches)
        assert recommendation == "update_existing"

    def test_moderate_similarity_recommendation(self):
        """Should recommend review_matches for moderate similarity."""
        service = RequirementDeduplicationService()
        near_matches = [
            DuplicateMatch(
                requirement_id=1,
                req_code="REQ-001",
                title="Test",
                description=None,
                acceptance_criteria=[],
                similarity=0.88,
            )
        ]
        recommendation = service.get_recommendation(None, near_matches)
        assert recommendation == "review_matches"

    def test_no_match_recommendation(self):
        """Should recommend create when no matches."""
        service = RequirementDeduplicationService()
        recommendation = service.get_recommendation(None, [])
        assert recommendation == "create"


class TestServiceCache:
    """Tests for get_deduplication_service() caching."""

    def test_same_project_returns_same_instance(self):
        """Should return same instance for same project."""
        service1 = get_deduplication_service("project-a")
        service2 = get_deduplication_service("project-a")
        assert service1 is service2

    def test_different_project_returns_different_instance(self):
        """Should return different instances for different projects."""
        service1 = get_deduplication_service("project-a")
        service2 = get_deduplication_service("project-b")
        assert service1 is not service2


class TestCosineSimilarity:
    """Tests for _cosine_similarity() method."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity 1.0."""
        service = RequirementDeduplicationService()
        vec = [1.0, 0.0, 0.5]
        assert service._cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity 0.0."""
        service = RequirementDeduplicationService()
        vec1 = [1.0, 0.0]
        vec2 = [0.0, 1.0]
        assert service._cosine_similarity(vec1, vec2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Opposite vectors should have similarity -1.0."""
        service = RequirementDeduplicationService()
        vec1 = [1.0, 0.0]
        vec2 = [-1.0, 0.0]
        assert service._cosine_similarity(vec1, vec2) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        """Empty vectors should return 0.0."""
        service = RequirementDeduplicationService()
        assert service._cosine_similarity([], []) == 0.0
        assert service._cosine_similarity([1.0], []) == 0.0

    def test_different_length_vectors(self):
        """Different length vectors should return 0.0."""
        service = RequirementDeduplicationService()
        assert service._cosine_similarity([1.0, 2.0], [1.0]) == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
