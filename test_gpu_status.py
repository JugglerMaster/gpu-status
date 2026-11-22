#!/usr/bin/env python3
"""Automated tests for gpu-status: nvidia-smi parsing + tok/s computation.

Run:  python -m unittest test_gpu_status.py -v
      (or: pytest test_gpu_status.py)
"""
import unittest

import gpu_status


class TestParseNvidiaCsv(unittest.TestCase):
    def test_real_ollm_row(self):
        # From ollm: Tesla V100-16GB, fan [N/A], float power, leading space in name.
        text = "0, Tesla V100-PCIE-16GB, 10137, 16384, 99, 78, 60.04, [N/A]\n"
        rows = gpu_status.parse_nvidia_csv(text)
        self.assertEqual(len(rows), 1)
        g = rows[0]
        self.assertEqual(g["index"], 0)
        self.assertEqual(g["name"], "Tesla V100-PCIE-16GB")
        self.assertEqual(g["memory.used"], 10137)
        self.assertEqual(g["memory.total"], 16384)
        self.assertEqual(g["utilization.gpu"], 99)
        self.assertEqual(g["temperature.gpu"], 78)
        self.assertAlmostEqual(g["power.draw"], 60.04)
        self.assertIsNone(g["fan.speed"])

    def test_multi_gpu(self):
        text = (
            "0, Tesla V100-PCIE-16GB, 10137, 16384, 99, 78, 60.04, [N/A]\n"
            "1, Tesla V100-PCIE-16GB, 4096, 16384, 12, 61, 30.5, 35\n"
        )
        rows = gpu_status.parse_nvidia_csv(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["index"], 0)
        self.assertEqual(rows[1]["index"], 1)
        self.assertEqual(rows[1]["fan.speed"], 35)
        self.assertEqual(rows[1]["power.draw"], 30.5)

    def test_skips_malformed_rows(self):
        text = (
            "0, Tesla V100-PCIE-16GB, 10137, 16384, 99, 78, 60.04, [N/A]\n"
            "bad row with too few fields\n"
            "9,9,9,9,9,9,9,9,9\n"  # too many fields
        )
        rows = gpu_status.parse_nvidia_csv(text)
        self.assertEqual(len(rows), 1)

    def test_empty(self):
        self.assertEqual(gpu_status.parse_nvidia_csv(""), [])
        self.assertEqual(gpu_status.parse_nvidia_csv("\n\n"), [])

    def test_whole_float_becomes_int(self):
        g = gpu_status.parse_nvidia_csv("0, X, 100, 200, 50, 60, 70.0, 80\n")[0]
        self.assertEqual(g["power.draw"], 70)
        self.assertEqual(g["fan.speed"], 80)

    def test_blank_and_na(self):
        g = gpu_status.parse_nvidia_csv("0, X, 100, 200, 50, 60, 70, \n")[0]
        self.assertIsNone(g["fan.speed"])


class TestTokenRate(unittest.TestCase):
    def test_idle_or_null(self):
        r = gpu_status.TokenRate()
        self.assertIsNone(r.update(None, 0.0))
        self.assertIsNone(r.update({"phase": "idle"}, 1.0))

    def test_first_sample_no_rate(self):
        r = gpu_status.TokenRate()
        self.assertIsNone(r.update({"generated": 0, "prompt_tokens": 100}, 0.0))

    def test_rate_within_request(self):
        r = gpu_status.TokenRate()
        r.update({"generated": 0, "prompt_tokens": 100}, 0.0)
        self.assertAlmostEqual(r.update({"generated": 10, "prompt_tokens": 100}, 1.0), 10.0)
        self.assertAlmostEqual(r.update({"generated": 20, "prompt_tokens": 100}, 2.0), 10.0)

    def test_no_rate_when_not_advanced(self):
        r = gpu_status.TokenRate()
        r.update({"generated": 0, "prompt_tokens": 100}, 0.0)
        r.update({"generated": 10, "prompt_tokens": 100}, 1.0)  # rate 10
        self.assertIsNone(r.update({"generated": 10, "prompt_tokens": 100}, 2.0))  # flat

    def test_new_request_resets(self):
        r = gpu_status.TokenRate()
        r.update({"generated": 0, "prompt_tokens": 100}, 0.0)
        r.update({"generated": 10, "prompt_tokens": 100}, 1.0)
        self.assertIsNone(r.update({"generated": 0, "prompt_tokens": 200}, 2.0))  # new request

    def test_too_close_no_rate(self):
        r = gpu_status.TokenRate(min_window=0.4)
        r.update({"generated": 0, "prompt_tokens": 100}, 0.0)
        self.assertIsNone(r.update({"generated": 10, "prompt_tokens": 100}, 0.2))  # < 0.4s

    def test_missing_generated_key(self):
        r = gpu_status.TokenRate()
        r.update({"phase": "reading prompt", "prompt_tokens": 100}, 0.0)
        self.assertIsNone(r.update({"phase": "generating", "prompt_tokens": 100}, 1.0))


if __name__ == "__main__":
    unittest.main()
