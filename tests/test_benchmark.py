import importlib
import importlib.util
import json
from pathlib import Path
import stat
import tarfile
import zipfile

import numpy as np
import pytest
import soundfile as sf

from zonepick.algorithms import AlgorithmInput, Region, get_algorithm
from zonepick.application.datasets import dataset_entries, inspect_datasets
from zonepick.audio import speech_segment
from zonepick.regions.car_zones import ZONE_ORDER
from zonepick.simulation import convolve, distances, propagation_seconds
from zonepick.simulation.car_geometry import LAYOUT_SIZES, load_car_geometry
from zonepick.simulation.car_scene import NoiseMetadata, SceneMetadata, SourceMetadata, build_car_scene
from zonepick.simulation.mcvampire import load_measurement
from zonepick.workbench.compare import ScenarioBundle, apply_algorithm
from zonepick.workbench.noise import NoiseConfig, inject_noise, list_local_recordings
from zonepick.workbench.splits import SplitConfig, build_split, speech_identity


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_archives", ROOT / "scripts/verify_archives.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify


@pytest.mark.parametrize("filename, symlink", [("../outside", False), ("/rooted", False), ("link", True)])
def test_archive_rejects_unsafe_members(tmp_path, monkeypatch, filename, symlink):
    monkeypatch.chdir(tmp_path)
    raw = Path("data/raw")
    raw.mkdir(parents=True)
    archive = raw / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        entry = zipfile.ZipInfo(filename)
        if symlink:
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(entry, b"content")
    dest = raw / "dest"
    dest.mkdir()
    with pytest.raises(ValueError):
        load_verifier()(archive, dest, extract=True)
    assert not list(dest.iterdir())
    assert archive.exists()


def test_archive_crc_compare_and_existing_destination(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = Path("data/raw")
    raw.mkdir(parents=True)
    archive = raw / "download.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("release/a", b"content")
    dest = raw / "data"
    dest.mkdir()
    verify = load_verifier()
    assert verify(archive, dest, extract=True)["files"] == 1
    with pytest.raises(FileExistsError):
        verify(archive, dest, extract=True)
    (dest / "release/a").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="Content mismatch"):
        verify(archive, dest)


def test_archive_rejects_symlink_to_external_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = Path("data/raw")
    raw.mkdir(parents=True)
    outside = tmp_path / "shared.zip"
    outside.write_bytes(b"original")
    (raw / "download.zip").symlink_to(outside)
    with pytest.raises(ValueError):
        load_verifier()(raw / "download.zip", raw / "destination")
    assert outside.read_bytes() == b"original"


def test_tar_verifies_existing_bytes_without_removing_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = Path("data/raw")
    raw.mkdir(parents=True)
    destination = raw / "dataset"
    destination.mkdir()
    target = destination / "speech.wav"
    target.write_bytes(b"original")
    archive = raw / "speech.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(target, arcname="speech.wav")
    verify = load_verifier()
    assert verify(archive, destination)["files"] == 1
    target.write_bytes(b"modified")
    with pytest.raises(ValueError, match="Content mismatch"):
        verify(archive, destination)
    assert archive.exists()


def test_speech_identity_and_official_split(tmp_path):
    paths = ["train-clean-100/12/80/12-80-0000.flac", "dev-clean/50/80/50-80-0000.flac",
             "test-clean/81/80/81-80-0000.flac"]
    assert speech_identity(paths[0], "librispeech")[0] == "librispeech:12"
    with pytest.raises(ValueError):
        speech_identity("train-clean-100/13/80/12-80-0000.flac", "librispeech")
    m = build_split(paths, tmp_path, SplitConfig(), corpus="librispeech", official=True)
    assert [m.paths_for(key) for key in ("train", "val", "test")] == [[p] for p in paths]


def test_aishell_cross_subset_and_stable_zero_ratio(tmp_path):
    paths = [f"{subset}/wav/SSB{speaker:04}/SSB{speaker:04}0001.wav"
             for subset in ("train", "test") for speaker in range(1, 7)]
    cfg = SplitConfig(train_ratio=.5, val_ratio=0, test_ratio=.5)
    m = build_split(paths, tmp_path, cfg, corpus="aishell3")
    other = build_split(reversed(paths), tmp_path, cfg, corpus="aishell3")
    assert m.content_hash == other.content_hash
    assert not m.paths_for("val")
    assert set(m.splits["train"]).isdisjoint(m.splits["test"])
    assert all(len(recordings) == 2 for split in m.splits.values() for recordings in split.values())
    assert speech_identity(paths[0], "aishell3")[0] == "aishell3:SSB0001"
    with pytest.raises(ValueError):
        build_split(["unparseable.wav"], tmp_path, cfg, corpus="aishell3")
    out = m.write(tmp_path / "manifest.json")
    with pytest.raises(FileExistsError):
        other.write(out)


def test_noise_group_mapping_and_total_snr(tmp_path):
    base = np.linspace(.001, .007, 100)
    for i in range(17):
        directory = tmp_path / f"label{i}_16k" / f"label{i}"
        directory.mkdir(parents=True)
        for channel in range(1, 17):
            sf.write(directory / f"ch{channel:02}.wav", channel * base, 8000, subtype="FLOAT")
    groups = list_local_recordings(tmp_path)
    assert len(groups) == 17 and groups[0].channel_ids[0] == "ch01"
    cfg = NoiseConfig(enabled=True, kinds=["dns_noise"], dns_root=tmp_path, seed=7,
                      spatial="captured", captured_channels=(1, 3), max_sources=3, snr_db=(10, 10))
    mics = np.zeros((2, 3))
    mixture = np.ones((2, 300))
    metadata = {}
    noisy, noise = inject_noise(mixture, mixture[1], 16000, mics, cfg,
                                reference_channel=1, metadata=metadata)
    np.testing.assert_allclose(noisy, mixture + noise)
    np.testing.assert_allclose(noise[0] * 2, noise[1])
    assert np.isclose(10 * np.log10(np.dot(mixture[1], mixture[1]) / np.dot(noise[1], noise[1])), 10)
    assert len(metadata["recordings"]) > 1
    assert metadata["recordings"][0]["channel_ids"] == ["ch02", "ch04"]
    cfg.captured_channels = (1, 16)
    with pytest.raises(ValueError, match="mapping"):
        inject_noise(mixture, mixture[1], 16000, mics, cfg)


def test_geometry_maps_boundaries_and_array_order(tmp_path):
    geometry = load_car_geometry()
    assert geometry.zones.zone_id((.8, 1.4, 1)) == "RR"
    assert [geometry.zones.zone_id(p) for p in geometry.seats] == list(ZONE_ORDER)
    assert [geometry.layout(i).channel_ids for i in LAYOUT_SIZES] == [
        ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7"), ("M0", "M1", "M2", "M3", "M4", "M7"),
        ("M0", "M3", "M4", "M7"), ("M0", "M3", "M8"), ("M9", "M8")
    ]
    actual = geometry.layout(2)
    for measure in (distances, propagation_seconds):
        np.testing.assert_allclose(measure((.4, 1, 1.1), actual.microphone_positions),
                                   measure((1.2, 1, 1.1), actual.microphone_positions))
    with pytest.raises(ValueError):
        geometry.zones.zone_id((0, 1, 1))
    arrays = json.loads((ROOT / "configs/arrays/car_array_family_v0.json").read_text())
    arrays["layouts"]["2"]["channel_ids"] = ["M8", "M8"]
    bad = tmp_path / "arrays.json"
    bad.write_text(json.dumps(arrays))
    with pytest.raises(ValueError):
        load_car_geometry(array_path=bad)


@pytest.mark.parametrize("count", [1, 2, 4, 5])
def test_fixed_zone_build_pairing_and_additivity(count):
    geometry = load_car_geometry()
    labels = {1: ("FL",), 2: ("FL", "FL"), 4: ZONE_ORDER, 5: ("FL", "FL", "RL", "RR", None)}[count]
    points = [p for group in geometry.source_candidates for p in group]
    sources = tuple(SourceMetadata(f"s{i}", points[i], zone, f"recording{i}", 4, i + 1,
                                   ((2, 5),) if i else (), f"rir{i}")
                    for i, zone in enumerate(labels))
    meta = SceneMetadata("event", "fixture", "val", 12, 16000, 16, sources,
                         (NoiseMetadata("recorded", 0, 1, "simulated"),), "candidate", {}, "fixture")
    speech = np.stack([np.full(16, i + 1.) for i in range(count)])
    rirs = np.tile(np.arange(1, 11)[None, :, None], (count, 1, 1))
    noise = np.ones((10, 16))
    scene = build_car_scene(geometry, meta, speech, rirs, noise)
    np.testing.assert_allclose(scene.mixture_master, scene.source_components.sum(axis=0) + noise)
    np.testing.assert_allclose(scene.zone_components.sum(axis=0), scene.source_components[
        [i for i, zone in enumerate(labels) if zone is not None]].sum(axis=0))
    np.testing.assert_allclose(scene.interference("FL"), scene.source_components[
        [i for i, zone in enumerate(labels) if zone != "FL"]].sum(axis=0))
    assert scene.zone_occupancy.tolist() == [z in labels for z in ZONE_ORDER]
    assert not scene.zone_activity[0, :2].any()
    assert scene.zone_activity[0, 3] == (count in (2, 5))
    permuted = SceneMetadata(**{**vars(meta), "sources": sources[::-1]})
    shuffled = build_car_scene(geometry, permuted, speech[::-1], rirs[::-1], noise)
    np.testing.assert_allclose(scene.zone_components, shuffled.zone_components)
    for size in LAYOUT_SIZES:
        payload = scene.metadata_for(size)
        assert payload["scene_id"] == "event"
        assert payload["public"]["zone_order"] == ZONE_ORDER
        json.dumps(payload, allow_nan=False)
        public = scene.public_input(size)
        np.testing.assert_array_equal(public.mixture, geometry.layout(size).select(scene.mixture_master))
        assert set(vars(public)) == {"mixture", "sample_rate", "layout", "geometry"}


def test_algorithm_isolation_oracle_and_mvdr(monkeypatch):
    bench = importlib.import_module("zonepick.workbench.compare")
    region = Region(np.array([1., 2]), .3, 1.1)
    bundle = ScenarioBundle(np.ones((2, 512)), 16000, np.array([[0, 0, 0], [.1, 0, 0]]), 0, region, {})

    class Mutator:
        def enhance(self, inp):
            inp.mixture[:] = 0
            inp.microphones[:] = -10
            inp.region.center[:] = -100
            return inp.mixture[0]

    original = bench.get_algorithm
    monkeypatch.setattr(bench, "get_algorithm", lambda name, **params: Mutator() if name == "mutator"
                        else original(name, **params))
    assert not apply_algorithm(bundle, "mutator")[0].any()
    assert (apply_algorithm(bundle, "identity")[0] == 1).all()
    assert np.all(bundle.microphones >= 0) and np.all(bundle.region.center > 0)
    monkeypatch.setattr(bench, "registered_classes", lambda: {"oracle": type("Oracle", (), {"kind": "oracle"})})
    with pytest.raises(ValueError, match="Oracle"):
        bench.compare({}, {}, ["oracle"])
    algorithm = get_algorithm("mvdr", diagonal_load=0)
    for signal in (np.zeros_like(bundle.mixture), bundle.mixture.astype(np.float32)):
        result = algorithm.enhance(AlgorithmInput(signal, 16000, bundle.microphones, 0, region))
        assert np.isfinite(result).all()
        if not signal.any():
            assert not result.any()


def test_invalid_reference_rejected_before_indexing(monkeypatch):
    bench = importlib.import_module("zonepick.workbench.compare")

    cfg = {"backend": "free_field", "region": {"center": [1, 2], "radius": 1, "steering_height": 1},
           "sample_rate": 16000, "reference_channel": 4}
    mics = np.zeros((2, 3))
    monkeypatch.setattr(bench, "prepare_simulation", lambda *args: (
        np.zeros((2, 16)), np.zeros((2, 2, 16)), mics, mics, [0, 1]))
    with pytest.raises(ValueError, match="参考麦克风"):
        bench.prepare_scenario(cfg, {})


def test_real_car_resources_when_present():
    entries = dataset_entries(ROOT / "configs/datasets.example.yaml")
    assert entries["mcvampire"]["path"] == Path("data/raw/McVAMPIRE")
    assert entries["cavemove"]["path"] == Path("data/raw/CAVEMOVE/cavemove_dataset")
    mcvampire = ROOT / entries["mcvampire"]["path"]
    cavemove = ROOT / entries["cavemove"]["path"]
    librispeech = ROOT / entries["librispeech"]["path"]
    if not (mcvampire / "geometry.mat").is_file() or not cavemove.is_dir() or not librispeech.is_dir():
        pytest.skip("locally downloaded resources are absent")
    speech = speech_segment(next(librispeech.rglob("*.flac")), 16000, 2048)
    responses, mics, _ = load_measurement(mcvampire, [{"seat": 1, "azimuth": 0}], [0, 2])
    rendered = convolve(speech, responses[0])
    assert rendered.shape == (2, 2048)
    assert np.isfinite(rendered).all() and rendered.any()
    config = NoiseConfig(enabled=True, kinds=["driving"], spatial="captured", captured_channels=(0, 2),
                         driving_root=mcvampire / "driving_noise", max_sources=1)
    noisy, noise = inject_noise(rendered, rendered[0], 16000, mics, config)
    assert noise.any() and np.isfinite(noisy).all()
    assert inspect_datasets({"cavemove": cavemove})["cavemove"]["audio_readable"]
