"""Semantic version rules for local builds and public releases.

Regular application builds use stable MAJOR.MINOR.PATCH versions. Prerelease
and build metadata remain reserved until the updater workflow supports them.
"""
import argparse
import re


_STABLE_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)
_CHANGE_TYPES = {"major", "minor", "patch"}


def _parts(version):
    if not isinstance(version, str) or not _STABLE_VERSION.fullmatch(version):
        raise ValueError("Expected stable MAJOR.MINOR.PATCH without leading zeros")
    return tuple(int(part) for part in version.split("."))


def next_version(current, change_type):
    """Return the next SemVer for a breaking, compatible, or fix-only change."""
    if change_type not in _CHANGE_TYPES:
        raise ValueError("change_type must be major, minor, or patch")
    major, minor, patch = _parts(current)
    if change_type == "major":
        return f"{major + 1}.0.0"
    if change_type == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def validate_new_version(version):
    _parts(version)
    return version


def validate_public_successor(previous_public, candidate, change_type):
    """Validate against the previous public stable release, never local builds."""
    _parts(previous_public)
    validate_new_version(candidate)
    expected = next_version(previous_public, change_type)
    if candidate != expected:
        raise ValueError(
            f"Previous public release {previous_public} with {change_type} change "
            f"requires {expected}, got {candidate}"
        )
    return candidate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate the next Semantic Version")
    parser.add_argument("current", help="Current stable version, without a v prefix")
    parser.add_argument("--change", choices=sorted(_CHANGE_TYPES), required=True)
    args = parser.parse_args()
    print(next_version(args.current, args.change))
