from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Hashable, Sequence


def accuracy(expected: Sequence[Hashable], predicted: Sequence[Hashable]) -> float:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted collections must have the same length.")
    if not expected:
        return 0.0
    return sum(left == right for left, right in zip(expected, predicted, strict=True)) / len(
        expected
    )


def macro_f1(expected: Sequence[str], predicted: Sequence[str]) -> float:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted collections must have the same length.")
    labels = sorted(set(expected) | set(predicted))
    if not labels:
        return 0.0
    scores: list[float] = []
    for label in labels:
        true_positive = sum(
            left == label and right == label
            for left, right in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            left != label and right == label
            for left, right in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            left == label and right != label
            for left, right in zip(expected, predicted, strict=True)
        )
        precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores)


def entity_scores(expected: Sequence[set[str]], predicted: Sequence[set[str]]) -> dict[str, float]:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted collections must have the same length.")
    def normalize(values: set[str]) -> set[str]:
        normalized: set[str] = set()
        for value in values:
            folded = unicodedata.normalize("NFKD", value.casefold().strip())
            folded = "".join(char for char in folded if not unicodedata.combining(char))
            compact = re.sub(r"[^a-z0-9]+", " ", folded).strip()
            if compact:
                normalized.add(compact)
        return normalized

    normalized_pairs = [
        (normalize(left), normalize(right))
        for left, right in zip(expected, predicted, strict=True)
    ]
    true_positive = sum(len(left & right) for left, right in normalized_pairs)
    false_positive = sum(len(right - left) for left, right in normalized_pairs)
    false_negative = sum(len(left - right) for left, right in normalized_pairs)
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def recall_at_k(retrieved: Sequence[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def reciprocal_rank(retrieved: Sequence[int], relevant: set[int]) -> float:
    for rank, identifier in enumerate(retrieved, start=1):
        if identifier in relevant:
            return 1 / rank
    return 0.0


def label_distribution(values: Sequence[str]) -> dict[str, int]:
    return dict(Counter(values))
