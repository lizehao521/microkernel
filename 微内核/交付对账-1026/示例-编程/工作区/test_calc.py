import unittest

from calc import mean


class TestMean(unittest.TestCase):
    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            mean([])

    def test_single(self):
        self.assertEqual(mean([5]), 5.0)

    def test_many(self):
        self.assertAlmostEqual(mean([1, 2, 3]), 2.0)


if __name__ == "__main__":
    unittest.main()
