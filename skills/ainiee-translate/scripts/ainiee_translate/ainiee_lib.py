"""The single seam to AiNiee. Puts AINIEE_REPO on sys.path and imports its
headless Domain/Cache types. Nothing else in this package imports AiNiee directly."""
import os
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class AiNiee:
    FileReader: Any
    FileOutputer: Any
    CacheManager: Any
    CacheProject: Any
    CacheItem: Any
    TranslationStatus: Any


def repo_path() -> str:
    return os.environ.get("AINIEE_REPO", "/Users/Anji/Desktop/AiNiee")


def load() -> AiNiee:
    repo = repo_path()
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from ModuleFolders.Domain.FileReader.FileReader import FileReader
    from ModuleFolders.Domain.FileOutputer.FileOutputer import FileOutputer
    from ModuleFolders.Service.Cache.CacheManager import CacheManager
    from ModuleFolders.Service.Cache.CacheProject import CacheProject
    from ModuleFolders.Service.Cache.CacheItem import CacheItem, TranslationStatus
    return AiNiee(FileReader, FileOutputer, CacheManager, CacheProject, CacheItem, TranslationStatus)
