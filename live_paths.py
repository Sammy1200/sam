"""Resolve live data/config paths with an external root priority."""
from __future__ import annotations

from dataclasses import dataclass
import os

import config


LIVE_ROOT_DIR = os.path.abspath(r"C:\py666")
LIVE_ACCOUNT_STATS_DB_PATH = os.path.join(LIVE_ROOT_DIR, "account_stats.sqlite3")
LIVE_LOCAL_SWITCH_ACCOUNT_CONFIG_PATH = os.path.join(LIVE_ROOT_DIR, "local_switch_account_config.json")
LIVE_LOCAL_WEB_SYNC_CONFIG_PATH = os.path.join(LIVE_ROOT_DIR, "local_web_sync_config.json")
LIVE_NICKNAME_TEMPLATE_DIR = os.path.join(LIVE_ROOT_DIR, "nichen")


@dataclass(frozen=True)
class ResolvedLivePath:
    path: str
    resolution_type: str
    preferred_path: str
    fallback_path: str


_LOGGED_PATH_KEYS: set[tuple[str, str, str]] = set()


def _normalize_path(path):
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(text)))


def _resolve_existing_path(preferred_path, fallback_path, exists_func):
    preferred_abs = _normalize_path(preferred_path)
    fallback_abs = _normalize_path(fallback_path)
    if preferred_abs and exists_func(preferred_abs):
        return ResolvedLivePath(
            path=preferred_abs,
            resolution_type="live_root",
            preferred_path=preferred_abs,
            fallback_path=fallback_abs,
        )
    return ResolvedLivePath(
        path=fallback_abs,
        resolution_type="project_fallback",
        preferred_path=preferred_abs,
        fallback_path=fallback_abs,
    )


def resolve_account_stats_db_path():
    return _resolve_existing_path(
        LIVE_ACCOUNT_STATS_DB_PATH,
        config.ACCOUNT_STATS_DB_PATH,
        os.path.isfile,
    )


def resolve_local_switch_account_config_path():
    return _resolve_existing_path(
        LIVE_LOCAL_SWITCH_ACCOUNT_CONFIG_PATH,
        config.LOCAL_SWITCH_ACCOUNT_CONFIG_PATH,
        os.path.isfile,
    )


def resolve_local_web_sync_config_path():
    return _resolve_existing_path(
        LIVE_LOCAL_WEB_SYNC_CONFIG_PATH,
        config.LOCAL_WEB_SYNC_CONFIG_PATH,
        os.path.isfile,
    )


def _normalize_optional_config_dir(raw_value, config_source_path):
    base_dir = os.path.dirname(_normalize_path(config_source_path)) or config.SCRIPT_DIR
    text = str(raw_value or "").strip()
    if not text:
        return ""

    expanded_value = os.path.expandvars(os.path.expanduser(text))
    if os.path.isabs(expanded_value):
        return os.path.abspath(expanded_value)
    return os.path.abspath(os.path.join(base_dir, expanded_value))


def resolve_nickname_template_dir(configured_value=None, config_source_path=""):
    project_fallback_dir = _normalize_path(config.NICKNAME_TEMPLATE_DIR)
    live_dir = _normalize_path(LIVE_NICKNAME_TEMPLATE_DIR)
    if live_dir and os.path.isdir(live_dir):
        return ResolvedLivePath(
            path=live_dir,
            resolution_type="live_root",
            preferred_path=live_dir,
            fallback_path=project_fallback_dir,
        )

    configured_dir = _normalize_optional_config_dir(configured_value, config_source_path)
    if configured_dir and os.path.isdir(configured_dir):
        return ResolvedLivePath(
            path=configured_dir,
            resolution_type="config_override",
            preferred_path=live_dir,
            fallback_path=project_fallback_dir,
        )

    return ResolvedLivePath(
        path=project_fallback_dir,
        resolution_type="project_fallback",
        preferred_path=live_dir,
        fallback_path=project_fallback_dir,
    )


def log_resolved_live_path(label, resolved_path, printer=print):
    if resolved_path is None:
        return

    path = _normalize_path(getattr(resolved_path, "path", ""))
    resolution_type = str(getattr(resolved_path, "resolution_type", "") or "").strip()
    if not path or not resolution_type:
        return

    key = (str(label or "").strip(), path, resolution_type)
    if key in _LOGGED_PATH_KEYS:
        return
    _LOGGED_PATH_KEYS.add(key)

    preferred_path = _normalize_path(getattr(resolved_path, "preferred_path", ""))
    fallback_path = _normalize_path(getattr(resolved_path, "fallback_path", ""))
    message = (
        f"[live-path] {label}：命中={path}，来源={resolution_type}，"
        f"live优先路径={preferred_path or '-'}，回退路径={fallback_path or '-'}"
    )
    printer(message)
