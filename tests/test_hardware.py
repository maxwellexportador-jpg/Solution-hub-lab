import unittest

from solution_print.hardware import (
    PROFILES,
    HardwareInfo,
    available_headroom_gb,
    check_requirements,
    classify_profile,
    detect_hardware,
    summarise,
)


def fake(ram: float, vram=None, gpu=None, cores: int = 4) -> HardwareInfo:
    return HardwareInfo(
        ram_total_gb=ram,
        ram_available_gb=ram * 0.8,
        cpu_cores=cores,
        gpu_name=gpu,
        vram_gb=vram,
        disk_free_gb=10.0,
        platform="test",
        python_version="3.12",
    )


class HardwareTests(unittest.TestCase):
    def test_detect_returns_real_values(self) -> None:
        info = detect_hardware()
        self.assertGreater(info.ram_total_gb, 0)
        self.assertGreaterEqual(info.cpu_cores, 1)
        self.assertGreaterEqual(info.ram_available_gb, 0)
        self.assertIsInstance(info.notes, list)

    def test_profiles_cover_required_tiers(self) -> None:
        keys = {profile.key for profile in PROFILES}
        self.assertEqual(
            keys,
            {"cpu-low", "cpu-8gb", "cpu-16gb", "cpu-32gb", "gpu-8gb", "gpu-24gb"},
        )

    def test_classify_cpu_profiles(self) -> None:
        self.assertEqual(classify_profile(fake(3.5)).key, "cpu-low")
        self.assertEqual(classify_profile(fake(8.0)).key, "cpu-8gb")
        self.assertEqual(classify_profile(fake(16.0)).key, "cpu-16gb")
        self.assertEqual(classify_profile(fake(31.0)).key, "cpu-32gb")
        self.assertEqual(classify_profile(fake(64.0)).key, "cpu-32gb")

    def test_classify_gpu_profiles(self) -> None:
        self.assertEqual(classify_profile(fake(16, vram=8, gpu="RTX 3070")).key, "gpu-8gb")
        self.assertEqual(classify_profile(fake(32, vram=24, gpu="RTX 3090")).key, "gpu-24gb")

    def test_requirements_respect_ram_and_vram(self) -> None:
        ok, reasons = check_requirements(16.0, None, fake(8.0))
        self.assertFalse(ok)
        self.assertTrue(any("RAM insuficiente" in item for item in reasons))

        ok, reasons = check_requirements(4.0, 8.0, fake(16.0))
        self.assertFalse(ok)
        self.assertTrue(any("nenhuma GPU" in item for item in reasons))

        ok, reasons = check_requirements(4.0, 8.0, fake(16.0, vram=4, gpu="RTX 3050"))
        self.assertFalse(ok)
        self.assertTrue(any("VRAM insuficiente" in item for item in reasons))

        ok, _ = check_requirements(4.0, 8.0, fake(16.0, vram=12, gpu="RTX 4070"))
        self.assertTrue(ok)

    def test_summary_is_human_readable(self) -> None:
        text = summarise(fake(8.0))
        self.assertIn("RAM", text)
        self.assertIn("cpu-8gb", text)

    def test_headroom_keeps_safety_margin(self) -> None:
        info = fake(8.0)
        self.assertAlmostEqual(available_headroom_gb(info), 8.0 * 0.8 - 8.0 * 0.2, places=2)


if __name__ == "__main__":
    unittest.main()
