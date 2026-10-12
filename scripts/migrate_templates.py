#!/usr/bin/env python3
"""
Migration script: convert old mailplate templates to .mplt format.

Reads templates from ~/.mailplate/templates/ and writes .mplt files
to the project's profile directory.
"""

from __future__ import annotations

import re
import sys
from configparser import ConfigParser
from pathlib import Path

SRC = Path.home() / ".mailplate"
TEMPLATES_SRC = SRC / "templates"
CONFIG_SRC = SRC / "config"

# Where to write the converted profiles
DST = Path.cwd() / "mailplate" / "profiles"
DST.mkdir(parents=True, exist_ok=True)

HELPER_SLOT_RE = re.compile(r"\$\(([^)]+)\)")
ENV_SLOT_RE = re.compile(r"\$\{([^}]+)\}")
CAPTURE_SLOT_RE = re.compile(r"%\(([^)]+)\)s")


def load_global_helpers() -> dict[str, str]:
    """Read the [helpers] section from the old config file."""
    if not CONFIG_SRC.exists():
        return {}
    cfg = ConfigParser()
    cfg.read(str(CONFIG_SRC))
    helpers: dict[str, str] = {}
    if cfg.has_section("helpers"):
        for name, command in cfg.items("helpers"):
            helpers[name] = command
    return helpers


def convert_value(value: str) -> str:
    """Replace old $(helper), ${env}, and %(capture)s syntax with {{ }}."""
    value = HELPER_SLOT_RE.sub(r"{{ helper:\1 }}", value)
    value = ENV_SLOT_RE.sub(r"{{ env:\1 }}", value)
    value = CAPTURE_SLOT_RE.sub(r"{{\1}}", value)
    return value


def migrate_template(path: Path, global_helpers: dict[str, str]) -> str | None:
    """
    Convert a single old-format template to .mplt content.

    Returns the .mplt content as a string, or None on failure.
    """
    text = path.read_text(encoding="utf-8")
    name = path.stem
    lines = text.splitlines()

    rules: list[str] = []
    headers: list[str] = []
    signature: list[str] = []
    profile_helpers: dict[str, str] = {}
    before_body: list[str] = []
    after_body: list[str] = []
    in_sig = False
    seen_keep_body = False
    has_htmlsig = False
    has_command_rule = False

    for line in lines:
        stripped = line.strip()

        # Comment line – skip
        if stripped.startswith("#"):
            continue

        # Blank line – preserve in greeting/closing context
        if not stripped:
            if in_sig:
                signature.append("")
            elif seen_keep_body:
                after_body.append("")
            else:
                before_body.append("")
            continue

        # =htmlsig path – HTML signature, not supported in new format
        if stripped.startswith("="):
            has_htmlsig = True
            continue

        # * N regexp – rule with weight
        if stripped.startswith("*"):
            rest = stripped[1:].strip()
            # Format: "* N REGEXP"
            parts = rest.split(" ", 1)
            if len(parts) == 2 and parts[0].isdigit():
                weight = int(parts[0])
                regex = parts[1].strip()
                # Identify whether this is a header or body rule.
                # Old rules use "HeaderName: pattern" – if we can split on
                # the first colon-space, treat as header rule.
                if ":" in regex and not regex.startswith("(?"):
                    hdr_name, _, hdr_re = regex.partition(":")
                    hdr_name = hdr_name.strip().lstrip("(?:")
                    # Clean up leading group constructs
                    if hdr_name.startswith("?:"):
                        hdr_name = hdr_name[2:].strip()
                    # Remove trailing )? etc.
                    hdr_re = hdr_re.strip()
                    # Escape the original regex into something that works
                    # in our format (HeaderName = regex).
                    if weight == 1:
                        rules.append(f"{hdr_name} = {hdr_re}")
                    else:
                        rules.append(f"{hdr_name}:{weight} = {hdr_re}")
                else:
                    if weight == 1:
                        rules.append(f"body = {regex}")
                    else:
                        rules.append(f"body:{weight} = {regex}")
            continue

        # ! N command – shell command as rule (scoring only)
        if stripped.startswith("!"):
            has_command_rule = True
            continue

        # @KEEP_* directives – skip in new format (all headers preserved)
        if stripped.startswith("@"):
            continue

        # --  (signature delimiter)
        if stripped == "-- " or stripped == "--":
            in_sig = True
            continue

        # =htmlsig path (already handled above but catch any stragglers)
        if "=htmlsig" in stripped:
            continue

        # If we see "From:" as header override, note it as header
        if (
            not in_sig
            and not seen_keep_body
            and re.match(r"^[A-Za-z0-9_-]+:", stripped)
        ):
            hdr_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)", stripped)
            if hdr_match:
                hdr_name = hdr_match.group(1)
                hdr_val = convert_value(hdr_match.group(2))
                headers.append(f"{hdr_name} = {hdr_val}")
                continue

        # If we're past "in_sig" but before body, it might be a plain text line
        if in_sig:
            signature.append(convert_value(stripped))
        elif seen_keep_body:
            after_body.append(convert_value(stripped))
        else:
            before_body.append(convert_value(stripped))

    # Check if this template uses helpers and add them
    for hname, hcmd in global_helpers.items():
        # Check if this helper is used in the template
        if f"{{{{ helper:{hname} }}}}" in text.replace("$(...)", ""):
            profile_helpers[hname] = hcmd

    # Read old config helpers if not already in global_helpers
    # (they are already loaded above)

    # Build the .mplt content
    out = []
    out.append("[profile]")
    out.append(f"name = {name}")

    if rules:
        out.append("")
        out.append("[rules]")
        out.extend(rules)

    if has_command_rule:
        out.append("")
        out.append("# TODO: ! (command) rules cannot be migrated automatically;")
        out.append(
            "# define a helper for the command and use {{ helper:name }} in a rule"
        )

    if headers:
        out.append("")
        out.append("[headers]")
        out.extend(headers)

    if has_htmlsig:
        out.append("")
        out.append("# TODO: =htmlsig directive cannot be migrated;")
        out.append("# embed the HTML signature file content manually")

    # Content before @KEEP_BODY → greeting
    # Content after @KEEP_BODY → closing
    before = [l for l in before_body if l]
    after = [l for l in after_body if l]
    # Also, anything before the first rule/header that isn't a header → greeting

    if before:
        out.append("")
        out.append("[greeting]")
        out.extend(before)

    if after:
        out.append("")
        out.append("[closing]")
        out.extend(after)

    if signature:
        out.append("")
        out.append("[signature]")
        out.extend(signature)

    if profile_helpers:
        out.append("")
        out.append("[helpers]")
        for hname, hcmd in profile_helpers.items():
            out.append(f"{hname} = {hcmd}")

    out.append("")
    return "\n".join(out)


def main() -> None:
    """Convert all old-format templates and write .mplt files."""
    global_helpers = load_global_helpers()
    print(f"Loaded {len(global_helpers)} global helpers", file=sys.stderr)

    templates = sorted(TEMPLATES_SRC.iterdir())
    converted = 0
    for tmpl in templates:
        if not tmpl.is_file():
            continue
        dst = DST / f"{tmpl.stem}.mplt"
        content = migrate_template(tmpl, global_helpers)
        if content is None:
            print(f"FAIL: {tmpl.name}", file=sys.stderr)
            continue
        dst.write_text(content, encoding="utf-8")
        print(f"  → {dst.name} ({len(content)} bytes)", file=sys.stderr)
        converted += 1

    print(f"\nConverted {converted} templates to {DST}", file=sys.stderr)


if __name__ == "__main__":
    main()
