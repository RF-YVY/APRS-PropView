"""Atomic configuration persistence and in-place runtime application."""
import os
import tempfile
from copy import deepcopy
from dataclasses import fields, is_dataclass
from pathlib import Path


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply_config(target, candidate):
    # Preserve nested references held by radio and weather services.
    for field in fields(candidate):
        value = getattr(candidate, field.name)
        current = getattr(target, field.name)
        if is_dataclass(value) and is_dataclass(current):
            apply_config(current, value)
        else:
            setattr(target, field.name, deepcopy(value))
