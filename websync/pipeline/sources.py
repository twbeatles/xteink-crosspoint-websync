"""Source identity for pipeline grouping, separate from human-readable names.

Identity follows the configured feed URL, so renaming a source preserves it.
Preview metadata is advisory: translation options always come from current config.
"""
from __future__ import annotations

import copy
import hashlib

from websync.i18n import t


def source_id(site: dict) -> str:
    url = (site.get("url") or "").strip()
    return "source_" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def source_metadata(site: dict) -> dict:
    return {"source_id": source_id(site), "source_url": site.get("url", ""),
            "site_name": site.get("name", "")}


def selected_source_groups(articles: list[dict], sites: list[dict], fallback: str) -> tuple[dict, dict]:
    """Return independent article copies grouped by identity and current source options.

    Old callers that supply only a name remain supported when unambiguous.
    An ambiguous legacy selection must be previewed again before sending; guessing
    could apply another feed's translation settings. Removed sources with explicit
    metadata can still be built/sent, with no inferred translation settings.
    """
    groups: dict[str, list[dict]] = {}
    options: dict[str, dict] = {}
    for original in articles:
        art = copy.deepcopy(original)
        name = art.get("site_name") or fallback
        identity = art.get("source_id")
        url = art.get("source_url")
        if identity or url:
            matches = [site for site in sites if
                       (not identity or source_id(site) == identity) and
                       (not url or site.get("url") == url)]
        else:
            matches = [site for site in sites if site.get("name") == name]
            if len(matches) > 1:
                raise ValueError(t("pipeline.selected.ambiguous_source"))
        if len(matches) > 1:
            raise ValueError(t("pipeline.selected.ambiguous_source"))
        site = matches[0] if matches else {}
        if site:
            art.update(source_metadata(site))
            name = art["site_name"] or fallback
        key = art.get("source_id") or ("url:" + url if url else name)
        art["_source_name"] = name
        groups.setdefault(key, []).append(art)
        options[key] = site
    return groups, options
