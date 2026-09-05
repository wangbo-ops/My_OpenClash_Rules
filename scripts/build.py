#!/usr/bin/env python3
"""Generate a personal template from a pinned upstream revision. Stdlib only."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "Aethersailor/Custom_OpenClash_Rules"
SOURCE_PATH = "cfg/Custom_Clash.ini"
GROUP = "custom_proxy_group="
RULE = "ruleset="
ANCHORS = ["ruleset=🎯 全球直连,[]GEOSITE,private",
           "ruleset=🎯 全球直连,[]GEOIP,private,no-resolve"]
PAYPAL_RULE_ANCHORS = ["ruleset=🌎 国外媒体,[]GEOSITE,category-entertainment",
                       "ruleset=🛒 国外电商,[]GEOSITE,category-ecommerce"]
PAYPAL_GROUP_ANCHORS = ["Ⓜ️ 微软服务", "🎮 游戏平台"]
HOME_GROUP_ANCHORS = ["🇰🇷 韩国节点", "🎯 全球直连"]
BUILTINS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}


class BuildError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BuildError(message)


def token(value):
    require(isinstance(value, str) and bool(value.strip()), "Empty/non-string setting")
    require(not any(c in value for c in "`\r\n"), "Invalid separator in setting")
    return value


def group_index(lines):
    result = {}
    for i, line in enumerate(lines):
        if line.startswith(GROUP):
            fields = line[len(GROUP):].split("`")
            require(len(fields) >= 3, "Malformed proxy group")
            name = fields[0]
            require(name not in result, f"Duplicate group: {name}")
            result[name] = (i, fields)
    return result


def to_select(fields):
    kind = fields[1]
    if kind == "select":
        require(not any(x.startswith(("http://", "https://")) for x in fields[2:]),
                f"Unexpected URL in select group: {fields[0]}")
        return list(fields)
    require(kind == "url-test", f"Unexpected upstream group type: {fields[0]} / {kind}")
    require(len(fields) >= 5 and fields[-2].startswith(("http://", "https://")),
            f"Unrecognized health-check layout: {fields[0]}")
    require(re.fullmatch(r"\d+(?:,\d*){0,2}", fields[-1]) is not None,
            f"Unrecognized health-check interval: {fields[0]}")
    return [fields[0], "select", *fields[2:-2]]


def insertion_anchor(items, anchors):
    for anchor in anchors:
        require(items.count(anchor) == 1, f"Missing/duplicate placement anchor: {anchor}")
    index = items.index(anchors[0])
    require(items[index:index + 2] == anchors,
            f"Upstream placement changed; review required: {anchors}")
    return index


def append_residential(fields, home_name):
    """Put the home group last among choices, before any health-check suffix."""
    if fields[1] == "select":
        choices, suffix = fields[2:], []
        require(not any(x.startswith(("http://", "https://")) for x in choices),
                f"Unexpected URL in select group: {fields[0]}")
    else:
        require(fields[1] in {"url-test", "fallback", "load-balance"},
                f"Unsupported residential choice group type: {fields[0]} / {fields[1]}")
        require(len(fields) >= 5 and fields[-2].startswith(("http://", "https://"))
                and re.fullmatch(r"\d+(?:,\d*){0,2}", fields[-1]) is not None,
                f"Unrecognized health-check layout: {fields[0]}")
        choices, suffix = fields[2:-2], fields[-2:]
    reference = "[]" + home_name
    return [*fields[:2], *[x for x in choices if x != reference], reference, *suffix]


def validate_references(lines):
    groups = group_index(lines)
    edges = {}
    for name, (_, fields) in groups.items():
        refs = [v[2:] for v in fields[2:] if v.startswith("[]")]
        for ref in refs:
            require(ref in groups or ref in BUILTINS, f"Missing group reference: {name} -> {ref}")
        edges[name] = [v for v in refs if v in groups]
    visiting, done = set(), set()

    def visit(name):
        require(name not in visiting, f"Circular group reference: {name}")
        if name in done:
            return
        visiting.add(name)
        for ref in edges[name]:
            visit(ref)
        visiting.remove(name)
        done.add(name)

    for name in groups:
        visit(name)
    for line in lines:
        if line.startswith(RULE):
            target = line[len(RULE):].split(",", 1)[0]
            require(target in groups or target in BUILTINS, f"Missing rule target: {target}")


def generate(source, settings):
    require(source.endswith("\n"), "Upstream must end with a newline")
    require("\r" not in source, "Unexpected upstream line endings")
    lines = source.splitlines()
    require(lines.count("[custom]") == 1, "Expected exactly one [custom] section")
    sections = [line for line in lines if line.startswith("[")]
    require(sections == ["[custom]"], "Unexpected upstream sections")
    for flag in ["enable_rule_generator=true", "overwrite_original_rules=true"]:
        require(lines.count(flag) == 1, f"Missing/changed upstream flag: {flag}")
    groups = group_index(lines)
    wanted = settings["select_groups"]
    require(isinstance(wanted, list) and wanted, "select_groups must be a nonempty list")
    for name in wanted:
        token(name)
    require(len(set(wanted)) == len(wanted), "Duplicate select_groups setting")
    residential = settings["residential"]
    paypal = settings["paypal"]
    home_name, pay_name = token(residential["name"]), token(paypal["name"])
    require(home_name != pay_name, "Personal group names must differ")
    for name in [home_name, pay_name]:
        require("," not in name, "Comma in custom group name")
        require(name not in groups, f"Upstream now defines personal group {name}; review required")
    home_filter = token(residential["filter"])
    re.compile(home_filter)
    choices = paypal["choices"]
    require(isinstance(choices, list) and choices, "PayPal requires choices")
    for name in choices:
        token(name)
    require(len(set(choices)) == len(choices), "Duplicate PayPal choices")
    require(type(paypal["include_all_nodes"]) is bool, "include_all_nodes must be boolean")
    require(not any(re.search(r",\[\]GEOSITE,paypal(?:,|$)", line, re.I)
                    for line in lines if line.startswith(RULE)),
            "Upstream now contains a PayPal GeoSite rule; review required")
    for anchor in ANCHORS:
        require(lines.count(anchor) == 1, f"Missing/duplicate rule anchor: {anchor}")
    require([line for line in lines if line.startswith(RULE)][:2] == ANCHORS,
            "Upstream private rule prefix changed; review required")
    insertion_anchor([line for line in lines if line.startswith(RULE)], PAYPAL_RULE_ANCHORS)
    insertion_anchor(list(groups), PAYPAL_GROUP_ANCHORS)
    insertion_anchor(list(groups), HOME_GROUP_ANCHORS)

    replacements = {}
    expected_groups = {}
    for name in wanted:
        require(name in groups, f"Upstream group missing or renamed: {name}")
    for name, (index, fields) in groups.items():
        modified = to_select(fields) if name in wanted else list(fields)
        regional = name in wanted or re.fullmatch(r"[\U0001F1E6-\U0001F1FF]{2}\s+.+节点", name)
        if name not in {"🎯 全球直连", "🔀 非标端口", home_name} and not regional:
            modified = append_residential(modified, home_name)
        if modified != fields:
            expected_groups[name] = modified
            replacements[index] = GROUP + "`".join(modified)

    home_line = GROUP + "`".join([home_name, "select", home_filter])
    pay_fields = [pay_name, "select", *["[]" + v for v in choices]]
    if paypal["include_all_nodes"]:
        pay_fields.append(".*")
    pay_fields = append_residential(pay_fields, home_name)
    pay_line = GROUP + "`".join(pay_fields)
    rule_line = RULE + pay_name + ",[]GEOSITE,paypal"
    insertions = {
        lines.index(PAYPAL_RULE_ANCHORS[0]): rule_line,
        groups[PAYPAL_GROUP_ANCHORS[0]][0]: pay_line,
        groups[HOME_GROUP_ANCHORS[0]][0]: home_line,
    }
    output, origins = [], []
    for i, line in enumerate(lines):
        output.append(replacements.get(i, line))
        origins.append(i)
        if i in insertions:
            output.append(insertions[i])
            origins.append(None)

    # Check that every unowned source line survives in its original order.
    require([i for i in origins if i is not None] == list(range(len(lines))),
            "Unexpected upstream line removal/reordering")
    for result, origin in zip(output, origins):
        if origin is not None and origin not in replacements:
            require(result == lines[origin], "Unexpected change outside personal settings")
    final_groups = group_index(output)
    for name, fields in expected_groups.items():
        require(final_groups[name][1] == fields, f"Group customization failed: {name}")
    require(output.count(home_line) == output.count(pay_line) == output.count(rule_line) == 1,
            "Personal group/rule count mismatch")
    for items, anchors, inserted in [
        ([line for line in output if line.startswith(RULE)], PAYPAL_RULE_ANCHORS, rule_line),
        (list(final_groups), PAYPAL_GROUP_ANCHORS, pay_name),
        (list(final_groups), HOME_GROUP_ANCHORS, home_name),
    ]:
        index = items.index(anchors[0])
        require(items[index:index + 3] == [anchors[0], inserted, anchors[1]],
                f"Personal placement mismatch: {inserted}")
    validate_references(output)
    header = ("; Generated personal derivative; edit custom/settings.json, not this file.\n"
              "; Upstream: https://github.com/" + UPSTREAM + "\n"
              "; Changes: PayPal rule/group, residential group/choices, regional select groups.\n"
              "; Template license: CC BY-SA 4.0; see LICENCE and NOTICE.md.\n")
    return header + "\n".join(output) + "\n"


def api_get(path):
    request = urllib.request.Request("https://api.github.com/repos/" + UPSTREAM + "/" + path,
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "My-OpenClash-Rules"})
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        request.add_header("Authorization", "Bearer " + github_token)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(2_000_001)
                require(len(raw) <= 2_000_000, "Upstream response exceeds expected size")
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def fetch_source():
    commit = api_get("commits/main")
    sha = commit["sha"]
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid upstream commit SHA")
    content = api_get("contents/" + SOURCE_PATH + "?ref=" + sha)
    require(content.get("encoding") == "base64", "Unexpected upstream content encoding")
    raw = base64.b64decode(content["content"])
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(blob_sha == content["sha"], "Upstream blob integrity mismatch")
    return raw.decode("utf-8"), sha


def atomic_write(path, text):
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(source, sha, settings_path, output_root):
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid upstream SHA")
    settings_text = settings_path.read_text(encoding="utf-8")
    settings = json.loads(settings_text)
    result = generate(source, settings)  # Nothing written before all checks pass.
    metadata = {
        "repository": UPSTREAM,
        "commit": sha,
        "source_path": SOURCE_PATH,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "settings_sha256": hashlib.sha256(settings_text.encode()).hexdigest(),
        "output_sha256": hashlib.sha256(result.encode()).hexdigest(),
    }
    atomic_write(output_root / "vendor/Custom_Clash.ini", source)
    atomic_write(output_root / "cfg/Custom_Clash.ini", result)
    atomic_write(output_root / "upstream-version.json",
                 json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Validated template: {len(group_index(result.splitlines()))} groups; upstream {sha}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Offline upstream snapshot")
    parser.add_argument("--upstream-sha", help="Commit SHA matching --source")
    parser.add_argument("--settings", type=Path, default=ROOT / "custom/settings.json")
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    require(bool(args.source) == bool(args.upstream_sha),
            "--source and --upstream-sha must be used together")
    if args.source:
        source, sha = args.source.read_bytes().decode("utf-8"), args.upstream_sha
    else:
        source, sha = fetch_source()
    run(source, sha, args.settings, args.output_root)


if __name__ == "__main__":
    try:
        main()
    except (BuildError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Build failed; no publication: {error}", file=sys.stderr)
        sys.exit(1)
