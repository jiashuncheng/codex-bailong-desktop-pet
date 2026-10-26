import unittest

from release_version import (
    next_version,
    validate_new_version,
    validate_public_successor,
)


class NumberingTests(unittest.TestCase):
    def test_semver_change_types_and_unbounded_segments(self):
        self.assertEqual(next_version("1.0.8", "patch"), "1.0.9")
        self.assertEqual(next_version("1.0.9", "patch"), "1.0.10")
        self.assertEqual(next_version("1.0.10", "minor"), "1.1.0")
        self.assertEqual(next_version("1.9.9", "major"), "2.0.0")
        self.assertEqual(next_version("0.6.50", "patch"), "0.6.51")

    def test_stable_semver_format_has_no_leading_zeros(self):
        for version in ("1.0.0", "1.10.0", "1.0.10", "12.34.56"):
            self.assertEqual(validate_new_version(version), version)
        for version in ("01.0.0", "1.00.0", "1.0.00", "v1.0.0", "1.0.0-alpha", "1.0.0+build"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_new_version(version)

    def test_public_release_uses_previous_public_and_declared_change_type(self):
        self.assertEqual(
            validate_public_successor("1.0.1", "1.0.2", "patch"), "1.0.2"
        )
        self.assertEqual(
            validate_public_successor("1.0.1", "1.1.0", "minor"), "1.1.0"
        )
        self.assertEqual(
            validate_public_successor("1.0.1", "2.0.0", "major"), "2.0.0"
        )
        with self.assertRaises(ValueError):
            validate_public_successor("1.0.1", "1.1.0", "patch")


if __name__ == "__main__":
    unittest.main()
