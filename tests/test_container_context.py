import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ContainerContextTests(unittest.TestCase):
    def test_source_data_package_is_not_excluded_from_build_context(self):
        patterns = {
            line.strip().rstrip("/")
            for line in (REPOSITORY_ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertNotIn("data", patterns)
        self.assertTrue((REPOSITORY_ROOT / "data" / "__init__.py").is_file())


if __name__ == "__main__":
    unittest.main()
