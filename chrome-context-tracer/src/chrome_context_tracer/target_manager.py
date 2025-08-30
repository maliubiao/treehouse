#!/usr/bin/env python3
"""
CDP Target Manager - Handles discovery and attachment to browser tabs (targets).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .i18n import _

if TYPE_CHECKING:
    from .cdp_client import DOMInspector


class TargetManager:
    """Manages browser targets (tabs)."""

    def __init__(self, client: "DOMInspector"):
        """
        Initializes the TargetManager.

        Args:
            client: The main DOMInspector client instance.
        """
        self.client = client

    def _is_valid_web_page(self, url: str) -> bool:
        """Check if a URL is a valid web page, filtering out internal/DevTools pages."""
        invalid_prefixes = ("devtools://", "chrome://", "edge://", "about:", "chrome-extension://")
        return not url.lower().startswith(invalid_prefixes) and url.lower().startswith(
            ("http://", "https://", "file://")
        )

    def _find_default_tab(self, valid_targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find the most likely active tab as a default choice using heuristics."""
        if not valid_targets:
            return None
        # Heuristic: An already attached target is a strong candidate.
        attached_targets = [t for t in valid_targets if t.get("attached")]
        if len(attached_targets) == 1:
            return attached_targets[0]
        # Fallback: The last target in the list is often the most recently opened/focused.
        return valid_targets[-1]

    async def find_tab_by_url(self, url_pattern: Optional[str] = None) -> Optional[str]:
        """Find a tab matching a URL pattern, or prompt the user if no pattern is given."""
        await asyncio.sleep(0.5)  # Allow time for targets to be discovered
        response = await self.client.send_command("Target.getTargets", use_session=False)
        targets = response.get("result", {}).get("targetInfos", [])
        valid_targets = [t for t in targets if t["type"] == "page" and self._is_valid_web_page(t["url"])]

        if url_pattern:
            for target in valid_targets:
                if url_pattern in target["url"]:
                    print(_("✅ Found matching tab: {url}", url=target["url"]))
                    return target["targetId"]
            print(_("❌ No tab found matching '{url_pattern}'.", url_pattern=url_pattern))
            if valid_targets:
                print(_("💡 Available tabs:"))
                for i, target in enumerate(valid_targets, 1):
                    print(f"  {i}. {target['url']}")
            return None

        # Interactive selection if no URL pattern is provided
        if not valid_targets:
            print(_("❌ No valid web page tabs found."))
            return None
        if len(valid_targets) == 1:
            selected_target = valid_targets[0]
            print(_("✅ Automatically selecting the only available tab: {url}", url=selected_target["url"]))
            return selected_target["targetId"]

        print(_("\nPlease select a tab to inspect:"))
        default_target = self._find_default_tab(valid_targets)
        default_index = -1
        for i, target in enumerate(valid_targets, 1):
            is_default = default_target and target["targetId"] == default_target["targetId"]
            default_marker = _(" (default)") if is_default else ""
            if is_default:
                default_index = i
            print(f"  * {i}. {target['url']}{default_marker}")

        while True:
            try:
                num_targets = len(valid_targets)
                prompt = _(
                    "\nEnter tab number (1-{num_targets}) [press Enter for default: {default_index}]: ",
                    num_targets=num_targets,
                    default_index=default_index,
                )
                choice_str = input(prompt).strip()
                choice = default_index if not choice_str else int(choice_str)
                if 1 <= choice <= num_targets:
                    selected = valid_targets[choice - 1]
                    print(_("✅ Selected tab: {url}", url=selected["url"]))
                    return selected["targetId"]
                print(_("Invalid choice. Please enter a number between 1 and {num_targets}.", num_targets=num_targets))
            except (ValueError, IndexError):
                print(_("Invalid input. Please enter a number."))
            except (KeyboardInterrupt, EOFError):
                print(_("\nSelection cancelled."))
                return None

    async def attach_to_tab(self, target_id: str) -> Optional[str]:
        """Attach to a specific target and return the session ID."""
        response = await self.client.send_command(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}, use_session=False
        )
        return response.get("result", {}).get("sessionId")
