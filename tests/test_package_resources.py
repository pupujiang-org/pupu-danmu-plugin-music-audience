"""Contracts for the declarative topic vocabulary and role interests.

The host reads a role's ``topic_interests`` and only accepts entries whose
``topic_id`` exists in the same version's vocabulary. A package that declares no
interest mapping stays "declared nothing" and never becomes eligible, so the
released resources must be checked here instead of only at runtime.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "music-audience"
ELIGIBLE_RELEVANCE = 60


def _load(name: str) -> dict[str, object]:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


class PackageResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.topics = _load("topics.json")
        self.personas = _load("personas.json")

    def test_topics_declare_the_version_two_shape(self) -> None:
        self.assertEqual(self.topics["format_version"], 2)
        entries = self.topics["topics"]
        self.assertIsInstance(entries, list)
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertEqual(set(entry), {"id", "label", "aliases"})
                self.assertNotRegex(entry["id"], r"\s")
                self.assertTrue(entry["label"].strip())
                self.assertLessEqual(len(entry["aliases"]), 8)
                for alias in entry["aliases"]:
                    self.assertTrue(alias.strip())

    def test_topic_ids_are_unique(self) -> None:
        ids = [entry["id"] for entry in self.topics["topics"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_role_interest_names_a_declared_topic(self) -> None:
        declared = {entry["id"] for entry in self.topics["topics"]}
        for role, persona in self.personas.items():
            with self.subTest(role=role):
                interests = persona.get("topic_interests", [])
                self.assertTrue(interests, "a released role must declare interests")
                for interest in interests:
                    self.assertEqual(set(interest), {"topic_id", "relevance"})
                    self.assertIn(interest["topic_id"], declared)
                    self.assertIsInstance(interest["relevance"], int)
                    self.assertGreaterEqual(interest["relevance"], 0)
                    self.assertLessEqual(interest["relevance"], 100)

    def test_every_role_has_a_topic_the_host_will_accept(self) -> None:
        for role, persona in self.personas.items():
            with self.subTest(role=role):
                self.assertTrue(
                    any(
                        interest["relevance"] >= ELIGIBLE_RELEVANCE
                        for interest in persona.get("topic_interests", [])
                    ),
                    "no topic clears the host eligibility threshold",
                )

    def test_topic_labels_stay_matchable_in_live_chat(self) -> None:
        for entry in self.topics["topics"]:
            with self.subTest(topic=entry["id"]):
                self.assertNotIn(" ", entry["label"])
                self.assertTrue(entry["label"].isprintable())


if __name__ == "__main__":
    unittest.main()
