"""Small four-zone scene builder consuming already prepared speech and RIRs."""

from dataclasses import asdict, dataclass
import json
from typing import Optional

import numpy as np

from zonepick.regions.car_zones import ZONE_ORDER
from zonepick.simulation import mix_sources
from zonepick.simulation.car_geometry import MIC_IDS, ArrayLayout, CarGeometry


@dataclass(frozen=True)
class SourceMetadata:
    speaker_id: str
    position: tuple
    zone_id: Optional[str]
    audio_id: str
    offset_samples: int
    gain: float
    active_intervals: tuple
    rir_id: str


@dataclass(frozen=True)
class NoiseMetadata:
    recording_id: str
    offset_samples: int
    gain: float
    rendering: str


@dataclass(frozen=True)
class SceneMetadata:
    scene_id: str
    dataset_version: str
    split: str
    seed: int
    sample_rate: int
    num_samples: int
    sources: tuple
    noise: tuple
    reference_definition: str
    generation_config: dict
    code_version: str
    snr_db: Optional[float] = None
    sir_db: Optional[float] = None
    schema_version: str = "1.0"
    snr_definition: str = "total_speech_power_at_master_reference"
    snr_reference_channel_id: str = "M0"
    virtual_reference_definition: Optional[str] = None
    master_channel_ids: tuple = MIC_IDS

    def validate(self, geometry):
        if (self.split not in ("train", "val", "test") or type(self.seed) is not int
                or type(self.sample_rate) is not int or self.sample_rate <= 0
                or type(self.num_samples) is not int or self.num_samples <= 0
                or not 1 <= len(self.sources) <= 5 or self.master_channel_ids != MIC_IDS
                or self.snr_reference_channel_id not in MIC_IDS):
            raise ValueError("Invalid scene split, dimensions or master channel order")
        _require_ids(self.scene_id, self.schema_version, self.dataset_version,
                     self.reference_definition, self.code_version, self.snr_definition)
        if self.virtual_reference_definition is not None:
            _require_ids(self.virtual_reference_definition)
        positions = set(geometry.microphones)
        for source in self.sources:
            _require_ids(source.speaker_id, source.audio_id, source.rir_id)
            position = geometry.zones.check_point(source.position)
            if position in positions or source.zone_id not in (*ZONE_ORDER, None):
                raise ValueError("Invalid or coincident source position or zone")
            positions.add(position)
            if type(source.offset_samples) is not int or source.offset_samples < 0:
                raise ValueError("Invalid source offset")
            if not np.isfinite(source.gain) or source.gain <= 0:
                raise ValueError("Invalid source gain")
            previous = 0
            for start, end in source.active_intervals:
                if type(start) is not int or type(end) is not int or not previous <= start < end <= self.num_samples:
                    raise ValueError("Speech activity must contain ordered, disjoint sample intervals")
                previous = end
        for recording in self.noise:
            _require_ids(recording.recording_id)
            if (type(recording.offset_samples) is not int or recording.offset_samples < 0
                    or not np.isfinite(recording.gain) or recording.gain < 0
                    or recording.rendering not in ("simulated", "measured_aligned")):
                raise ValueError("Invalid noise provenance")
        if any(value is not None and not np.isfinite(value) for value in (self.snr_db, self.sir_db)):
            raise ValueError("SNR and SIR must be finite if provided")
        if not isinstance(self.generation_config, dict):
            raise ValueError("Expected a generation configuration mapping")
        json.dumps(asdict(self), allow_nan=False)

    def to_dict(self, geometry, count):
        self.validate(geometry)
        layout = geometry.layout(count)
        return {
            "schema_version": self.schema_version, "dataset_version": self.dataset_version,
            "scene_id": self.scene_id, "split": self.split, "seed": self.seed,
            "public": {
                "sample_rate": self.sample_rate, "num_samples": self.num_samples,
                "room_id": geometry.room_id, "array_id": layout.array_id,
                "channel_ids": layout.channel_ids, "microphone_positions": layout.microphone_positions,
                "reference_channel": layout.reference_channel, "zone_order": ZONE_ORDER,
                "cabin": geometry.to_dict(),
            },
            "supervision": {"sources": [asdict(source) for source in self.sources],
                            "reference_definition": self.reference_definition,
                            "virtual_reference_definition": self.virtual_reference_definition},
            "simulation": {"noise": [asdict(record) for record in self.noise], "snr_db": self.snr_db,
                           "sir_db": self.sir_db, "snr_definition": self.snr_definition,
                           "master_channel_ids": self.master_channel_ids,
                           "snr_reference_channel_id": self.snr_reference_channel_id,
                           "generation_config": self.generation_config, "code_version": self.code_version},
        }


def _require_ids(*identifiers):
    if any(not isinstance(value, str) or not value.strip() for value in identifiers):
        raise ValueError("Identifiers and reference definitions must be nonempty strings")


@dataclass(frozen=True)
class FourZoneInput:
    mixture: np.ndarray
    sample_rate: int
    layout: ArrayLayout
    geometry: CarGeometry


@dataclass(frozen=True)
class FourZoneScene:
    geometry: CarGeometry
    metadata: SceneMetadata
    source_components: np.ndarray
    zone_components: np.ndarray
    noise_components: np.ndarray
    mixture_master: np.ndarray
    zone_occupancy: np.ndarray
    zone_activity: np.ndarray
    clean_zone_reference: np.ndarray
    clean_sources: np.ndarray

    @property
    def zone_members(self):
        return self.geometry.zones.members(tuple(source.zone_id for source in self.metadata.sources))

    def public_input(self, count):
        layout = self.geometry.layout(count)
        return FourZoneInput(layout.select(self.mixture_master), self.metadata.sample_rate,
                             layout, self.geometry)

    def physical_reference(self, count):
        """Return [4, M, T] isolated zones on the selected physical microphones."""
        return self.geometry.layout(count).select(self.zone_components)

    def interference(self, zone_id, *, include_noise=False):
        if zone_id not in ZONE_ORDER:
            raise ValueError(f"Unknown zone: {zone_id}")
        outside = [s.zone_id != zone_id for s in self.metadata.sources]
        interference = self.source_components[outside].sum(axis=0)
        return interference + self.noise_components if include_noise else interference

    def metadata_for(self, count):
        return self.metadata.to_dict(self.geometry, count)

    def validate_estimates(self, estimates):
        return _audio(estimates, (len(ZONE_ORDER), self.metadata.num_samples), "estimates")


def _audio(signal, shape, name):
    samples = np.asarray(signal, dtype=float)
    if samples.shape != shape or not np.isfinite(samples).all():
        raise ValueError(f"{name} must be finite with shape {shape}")
    return samples


def build_car_scene(geometry, metadata, speech, responses, noise=None):
    """Build one paired event. Each RIR must use the master M0–M9 channel order."""
    metadata.validate(geometry)
    length = metadata.num_samples
    shape = (len(MIC_IDS), length)
    count = len(metadata.sources)
    waveforms = _audio(speech, (count, length), "speech")
    if len(responses) != count:
        raise ValueError("Each source needs a master RIR")
    for rir in responses:
        rir = np.asarray(rir)
        if rir.ndim != 2 or rir.shape[0] != len(MIC_IDS) or not rir.shape[1] or not np.isfinite(rir).all():
            raise ValueError("RIR must be finite with shape [10, L]")
    gains = [source.gain for source in metadata.sources]
    mixture, components = mix_sources(waveforms, responses, gains)
    _audio(components, (count, *shape), "source components")
    noise = np.zeros(shape) if noise is None else _audio(noise, shape, "noise").copy()
    if noise.any() and not metadata.noise:
        raise ValueError("Nonzero noise requires provenance")
    zone_ids = tuple(source.zone_id for source in metadata.sources)
    memberships = geometry.zones.members(zone_ids)
    zones = np.stack([components[list(members)].sum(axis=0) for members in memberships])
    clean = waveforms * np.asarray(gains)[:, None]
    clean_zones = np.stack([clean[list(members)].sum(axis=0) for members in memberships])
    activity = np.zeros((len(ZONE_ORDER), length), dtype=bool)
    for index, members in enumerate(memberships):
        for member in members:
            for start, end in metadata.sources[member].active_intervals:
                activity[index, start:end] = True
    mixture = _audio(mixture + noise, shape, "mixture")
    return FourZoneScene(geometry, metadata, components, zones, noise, mixture,
                         np.asarray([bool(items) for items in memberships]), activity, clean_zones, waveforms.copy())
