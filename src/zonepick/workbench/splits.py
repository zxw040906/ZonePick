"""按命名空间隔离身份并生成可复现的划分。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re

import numpy as np


@dataclass
class SplitConfig:
    """划分参数，全部可外部调节。"""

    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    seed: int = 42
    strategy: str = "group"          # group（按说话人/会话）| file（仅用于无分组信息的数据）
    librispeech_speaker_pattern: str = r"(\d+)"  # 从 FLAC 路径提取说话人 ID

    def validate(self):
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if not np.isclose(total, 1.0, atol=1e-9):
            raise ValueError(f"划分比例之和须为 1.0，当前为 {total}")
        if min(self.train_ratio, self.val_ratio, self.test_ratio) < 0:
            raise ValueError("划分比例不可为负")
        if self.strategy not in ("group", "file"):
            raise ValueError("strategy 须为 group 或 file")


@dataclass
class SplitManifest:
    """冻结的划分结果。"""

    config: dict
    created_at: str
    splits: dict = field(default_factory=dict)   # {split: {group: [relative paths]}}

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @property
    def content_hash(self):
        payload = json.dumps({"config": self.config, "splits": self.splits}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(self.to_json() + "\n")
                stream.flush()
                os.link(temporary, path)
            finally:
                temporary.unlink()
        return path

    @classmethod
    def read(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def paths_for(self, split):
        """展平某集合的全部相对路径。"""
        return [p for paths in self.splits.get(split, {}).values() for p in paths]


CLEAN_SUBSETS = {"train-clean-100": "train", "train-clean-360": "train",
                 "dev-clean": "val", "test-clean": "test"}


def speech_identity(entry, corpus):
    """返回说话人、录音及官方子集，路径与文件名必须一致。"""
    path = Path(entry)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Recording path must stay inside its corpus: {entry}")
    if corpus == "librispeech":
        match = re.fullmatch(r"(\d+)-(\d+)-\d+\.flac", path.name)
        if (not match or len(path.parts) < 4 or
                path.parts[-3:-1] != match.groups()):
            raise ValueError(f"Invalid LibriSpeech recording: {entry}")
        speaker = match[1]
        subset = path.parts[-4]
    elif corpus == "aishell3":
        match = re.fullmatch(r"(SSB\d{4})\d{4}\.wav", path.name)
        if (not match or len(path.parts) < 4 or path.parts[-3:-1] != ("wav", match[1])
                or path.parts[-4] not in ("train", "test")):
            raise ValueError(f"Invalid AISHELL-3 recording: {entry}")
        speaker = match[1]
        subset = path.parts[-4]
    else:
        raise ValueError(f"Unknown speech corpus: {corpus}")
    return f"{corpus}:{speaker}", f"{corpus}:{path.stem}", subset


def build_split(entries, root, config, *, corpus=None, official=False):
    """按身份分组。通用条目支持显式文件分组和自定义身份正则。"""
    config.validate()
    groups = {}
    assignments = {}
    recordings = {name: set() for name in ("train", "val", "test")}
    recording_ids = {}
    if official and corpus != "librispeech":
        raise ValueError("Official split is only supported for LibriSpeech")
    if corpus and config.strategy != "group":
        raise ValueError("Speech corpora require speaker-disjoint grouping")
    for entry in sorted(set(map(str, entries))):
        if corpus:
            key, recording, subset = speech_identity(entry, corpus)
        else:
            match = re.search(config.librispeech_speaker_pattern, entry)
            if config.strategy == "group" and (not match or not match.lastindex):
                raise ValueError(f"Cannot parse identity: {entry}")
            key = entry if config.strategy == "file" else match[1]
            recording = entry
        groups.setdefault(key, []).append(entry)
        recording_ids[entry] = recording
        if official:
            if subset not in CLEAN_SUBSETS:
                raise ValueError(f"Unsupported official subset: {subset}")
            split = CLEAN_SUBSETS[subset]
            if assignments.setdefault(key, split) != split:
                raise ValueError(f"Speaker crosses official subsets: {key}")
    if not groups:
        raise ValueError(f"No recordings found: {root}")
    if not official:
        ratios = np.asarray([config.train_ratio, config.val_ratio, config.test_ratio])
        keys = np.random.default_rng(config.seed).permutation(sorted(groups))
        quotas = len(keys) * ratios / ratios.sum()
        counts = np.floor(quotas).astype(int)
        remainder = len(keys) - counts.sum()
        candidates = np.flatnonzero(ratios > 0)
        order = candidates[np.argsort(-(quotas - counts)[candidates], kind="stable")]
        counts[order[:remainder]] += 1
        if len(keys) >= len(candidates):
            for index in candidates[counts[candidates] == 0]:
                donor = np.argmax(counts - quotas + np.where(counts > 1, 0, -np.inf))
                counts[donor] -= 1
                counts[index] += 1
        start = 0
        for split, count in zip(recordings, counts):
            assignments.update(dict.fromkeys(keys[start:start + count], split))
            start += count
    splits = {name: {} for name in recordings}
    for key, paths in sorted(groups.items()):
        split = assignments[key]
        splits[split][key] = paths
        recordings[split].update(recording_ids[entry] for entry in paths)
    if len(set.union(*recordings.values())) != sum(map(len, recordings.values())):
        raise ValueError("Original recordings cross splits")
    return SplitManifest(
        config={**asdict(config), "corpus": corpus, "official": official},
        created_at=datetime.now(timezone.utc).isoformat(),
        splits=splits,
    )


def build_librispeech_split(root, config=None, *, official=False):
    root = Path(root)
    return build_split((p.relative_to(root) for p in root.rglob("*.flac")),
                       root, config or SplitConfig(), corpus="librispeech", official=official)


def build_aishell3_split(root, config=None):
    root = Path(root)
    return build_split((p.relative_to(root) for p in root.rglob("*.wav")),
                       root, config or SplitConfig(), corpus="aishell3")


def assert_no_test_leak(manifest, train_entries):
    test = set(manifest.paths_for("test"))
    leaked = test.intersection(str(e) for e in train_entries)
    if leaked:
        raise AssertionError(f"训练集包含 test 条目: {sorted(leaked)[:5]}")
    return True
