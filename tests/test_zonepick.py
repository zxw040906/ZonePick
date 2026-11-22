"""使用临时合成音频验证首版闭环。"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np
from scipy.io import savemat

from zonepick.algorithms.classical import das_weights, enhance, relative_delays
from zonepick.application import run
from zonepick.audio import analysis, read_audio, speech_segment, synthesis, write_audio
from zonepick.evaluation import si_sdr
from zonepick.regions import circle_members
from zonepick.simulation import free_field_rir, mix_sources, propagation_seconds
from zonepick.simulation.dechorate import load_measurement
from zonepick.simulation import mcvampire


class SignalTests(unittest.TestCase):
    def test_audio_file_channel_order_and_resampling(self):
        audio = np.array([[0.1, -0.2, 0.3, 0], [-0.4, 0.1, 0.2, 0.3]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            write_audio(path, audio, 16000)
            restored, rate = read_audio(path)
            self.assertEqual(rate, 16000)
            np.testing.assert_allclose(restored, audio)
            path = Path(directory) / "mono.wav"
            write_audio(path, audio[:1], 8000)
            self.assertEqual(speech_segment(path, 16000, 10).shape, (10,))

    def test_stft_istft_reconstruction_including_short_clip(self):
        for length in (19, 517):
            with self.subTest(length=length):
                audio = np.random.default_rng(42).normal(size=(3, length))
                frequencies, spectrum = analysis(audio, 16000, 128)
                self.assertEqual(spectrum.shape[:2], (3, len(frequencies)))
                restored = synthesis(spectrum, 16000, 128, length)
                np.testing.assert_allclose(restored, audio, atol=1e-12)

    def test_free_field_delays_and_units(self):
        microphones = [[2, 0, 0], [1, 0, 0], [3, 0, 0]]
        point = [0, 0, 0]
        np.testing.assert_allclose(propagation_seconds(point, microphones, 320),
                                   np.array([2, 1, 3]) / 320)
        np.testing.assert_allclose(relative_delays(point, microphones, 0, 320),
                                   np.array([0, -1, 1]) / 320)
        rir = free_field_rir(point, microphones, 16000, 320)
        np.testing.assert_array_equal(rir.argmax(axis=1), [100, 50, 150])
        np.testing.assert_allclose(rir.sum(axis=1), [0.5, 1, 1/3])

    def test_source_components_are_additive(self):
        speech = [np.array([1., 2., 3.]), np.array([3., 2., 1.])]
        impulse = np.array([[1., 0.], [0., 1.]])
        mixture, components = mix_sources(speech, [impulse, impulse], [1.0, 2.0])
        np.testing.assert_allclose(components, [[[1, 2, 3], [0, 1, 2]],
                                               [[6, 4, 2], [0, 6, 4]]], atol=1e-12)
        np.testing.assert_allclose(mixture, components.sum(axis=0))

    def test_circle_boundary(self):
        np.testing.assert_array_equal(
            circle_members([[0, 0, 100], [1, 0, 3], [1.01, 0, 0]], [0, 0], 1),
            [True, True, False],
        )

    def test_das_multiple_microphone_counts(self):
        rng = np.random.default_rng(2)
        audio = rng.normal(size=913)
        for count in (1, 3, 5, 8, 14):
            with self.subTest(channels=count):
                frequencies = np.fft.rfftfreq(128, 1 / 16000)
                weights = das_weights(frequencies, np.zeros(count))
                self.assertEqual(weights.shape, (65, count))
                out = enhance(np.tile(audio, (count, 1)), 16000, [[1, 0, 0]] * count,
                              [0, 0, 0], 0, n_fft=128)
                np.testing.assert_allclose(out, audio, atol=1e-12)

    def test_das_phase_aligns_later_channel(self):
        rate = 16000
        length = 4096
        samples = np.arange(length)
        # 两个采样点的相对时延，使用低频信号减小窗边缘影响。
        signal = np.sin(2 * np.pi * samples / 32)
        delayed = np.sin(2 * np.pi * (samples - 2) / 32)
        microphones = [[1, 0, 0], [1.04, 0, 0]]
        result = enhance(np.stack([signal, delayed]), rate, microphones, [0, 0, 0], 0,
                         n_fft=512, sound_speed=320)
        # 分帧相位补偿近似整数时移。反号或无对齐会产生远大于此的残差。
        np.testing.assert_allclose(result[512:-512], signal[512:-512], atol=5e-3)

    def test_si_sdr_uses_projection_and_requires_reference(self):
        target = [1., -1., 1., -1.]
        estimate = [3., -1., 1., -3.]
        self.assertAlmostEqual(si_sdr(estimate, target), 10 * np.log10(4))
        self.assertIsNone(si_sdr(estimate, [0, 0, 0, 0]))


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        rng = np.random.default_rng(42)
        for name in ("first.wav", "second.wav"):
            write_audio(self.root / name, rng.uniform(-0.1, 0.1, (1, 1024)), 16000)
        self.config = {
            "backend": "free_field", "sample_rate": 16000, "samples": 1024,
            "microphones": [[0, 0, 0], [0.2, 0, 0], [0.4, 0, 0]],
            "channels": [2, 0], "reference_channel": 1,
            "region": {"center": [1.05, 0], "radius": 0.4, "steering_height": 0},
            "sources": [
                {"file": "first.wav", "position": [1, 0, 0]},
                {"file": "second.wav", "position": [-1, 1, 0]},
            ],
            "seed": 42,
        }

    def test_repeat_and_recording_mode_without_truth(self):
        paths = {"librispeech": self.root}
        first, scores = run(self.config, paths, self.root)
        second, repeat_scores = run(self.config, paths, self.root)
        self.assertNotEqual(first, second)
        waveform, _ = read_audio(first / "enhanced.wav")
        np.testing.assert_array_equal(waveform, read_audio(second / "enhanced.wav")[0])
        self.assertEqual(scores["output_si_sdr_db"], repeat_scores["output_si_sdr_db"])
        resolved = json.loads((first / "scenario.json").read_text())
        self.assertEqual(resolved["resolved_microphones"], [[0.4, 0, 0], [0, 0, 0]])
        self.assertTrue(scores["reference_available"])

        recording = {
            "backend": "recording", "sample_rate": 16000,
            "input_wav": str(first / "mixture.wav"),
            "microphones": resolved["resolved_microphones"],
            "reference_channel": 1, "region": self.config["region"],
        }
        with patch("zonepick.application.prepare_simulation", side_effect=AssertionError("使用了仿真")):
            output, metrics = run(recording, {}, self.root)
        self.assertIsNone(metrics["input_si_sdr_db"])
        self.assertIsNone(metrics["output_si_sdr_db"])
        self.assertFalse((output / "target.wav").exists())
        np.testing.assert_allclose(read_audio(output / "enhanced.wav")[0], waveform, atol=1e-8)

    def test_missing_dataset_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "librispeech.*datasets.yaml"):
            run(self.config, {}, self.root)

    def test_sofa_channel_selection_tracks_geometry(self):
        coordinates = np.arange(15, dtype=float).reshape(5, 3)
        for source in (1, 2):
            path = self.root / f"dEchorate_room000000_src{source}_arr1_mics1-5.sofa"
            with h5py.File(path, "w") as fixture:
                fixture["Data.SamplingRate"] = [48000]
                ir = np.zeros((1, 5, 48000))
                ir[0, :, 0] = np.arange(1, 6)
                fixture["Data.IR"] = ir
                fixture["ReceiverPosition"] = coordinates
                fixture["SourcePosition"] = [[float(source), 0, 0]]
        responses, microphones, positions = load_measurement(self.root, 1, [4, 0, 2])
        np.testing.assert_array_equal(microphones, coordinates[[4, 0, 2]])
        np.testing.assert_array_equal(positions[:, 0], [1, 2])
        self.assertEqual(responses[0].shape, (3, 16000))
        np.testing.assert_allclose(responses[0][:, 0] / responses[0][1, 0], [5, 1, 3])

    def test_mcvampire_fixed_measurement_and_channel_selection(self):
        microphones = np.arange(42, dtype=float).reshape(14, 3)
        angles = np.column_stack((np.arange(-5, 6), np.zeros(11)))
        directions = np.tile([1.0, 0.0, 0.0], (11, 1))
        savemat(self.root / "geometry.mat", {
            "mic": [{"pos": row} for row in microphones],
            "mouth": [
                {"centerpos": [seat, 0, 0], "orientations_XYZ": directions, "orientations_AzEl": angles}
                for seat in range(1, 9)
            ],
        })
        ir_dir = self.root / "ir"
        ir_dir.mkdir()
        ir = np.zeros((14, 2040))
        ir[:, 0] = np.arange(1, 15)
        write_audio(ir_dir / "ir_mouth_pos2_0.wav", ir, 24000)
        responses, coords, positions = mcvampire.load_measurement(
            self.root, [{"seat": 2, "azimuth": 0}], [13, 0, 4],
        )
        self.assertEqual(responses[0].shape, (3, 1360))
        np.testing.assert_array_equal(coords, microphones[[13, 0, 4]])
        np.testing.assert_allclose(positions, [[2.07, 0, 0]])
        np.testing.assert_allclose(responses[0][:, 0] / responses[0][1, 0], [14, 1, 5])
        with self.assertRaisesRegex(ValueError, "无唯一"):
            mcvampire.load_measurement(self.root, [{"seat": 2, "azimuth": 90}], [0])


if __name__ == "__main__":
    unittest.main()
