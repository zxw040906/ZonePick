"""收尾清理：删除本次运行产物与可重建缓存。

只删除显式传入且位于项目根之内的目标，以及项目内的 __pycache__ / *.pyc。
用户配置（configs/local/）、版本库（.git/）、编辑器设置（.vscode/）一律不动。
"""

from pathlib import Path
import shutil


def cleanup_generated(targets, project_root):
    """删除给定目标与项目内的字节码缓存，返回被删目标数量。

    targets: 本次运行生成的目录/文件路径；位于 project_root 之外的忽略。
    """
    root = Path(project_root).resolve()
    removed = 0
    for target in targets:
        path = Path(target)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == root or root not in resolved.parents:
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=True)
            removed += 1
        elif resolved.exists():
            try:
                resolved.unlink()
                removed += 1
            except OSError:
                pass
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass
    return removed
