import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "tests/fixtures/standard.ini").read_text(encoding="utf-8")
        self.settings = json.loads((ROOT / "custom/settings.json").read_text(encoding="utf-8"))

    def output(self, source=None, settings=None):
        return build.generate(self.source if source is None else source,
                              self.settings if settings is None else settings)

    def test_personal_policy_and_rule_priority(self):
        output = self.output()
        groups = build.group_index(output.splitlines())
        for name in self.settings["select_groups"]:
            self.assertEqual(groups[name][1][1], "select")
            self.assertFalse(any(x.startswith("https://") for x in groups[name][1]))
        pay = groups[self.settings["paypal"]["name"]][1]
        self.assertEqual(pay[2], "[]🎯 全球直连")
        self.assertEqual(pay[-1], ".*")
        rules = [x for x in output.splitlines() if x.startswith("ruleset=")]
        self.assertEqual(rules[2], "ruleset=💳 PayPal,[]GEOSITE,paypal")

    def test_upstream_regex_improvements_survive(self):
        changed = self.source.replace("波特兰|", "新增美国城市|波特兰|", 1)
        fields = build.group_index(self.output(changed).splitlines())["🇺🇸 美国节点"][1]
        self.assertEqual(fields[1], "select")
        self.assertIn("新增美国城市|波特兰|", fields[2])

    def test_upstream_new_rule_and_group_survive(self):
        addition = "ruleset=新服务,[]GEOSITE,example\ncustom_proxy_group=新服务`select`[]🚀 手动选择\n"
        source = self.source.replace(";设置节点分组标志位", addition + ";设置节点分组标志位")
        output = self.output(source)
        for line in addition.splitlines():
            self.assertIn(line, output.splitlines())
        self.assertLess(output.index(addition.splitlines()[0]), output.index(addition.splitlines()[1]))

    def test_missing_or_renamed_group_stops_build(self):
        with self.assertRaises(build.BuildError):
            self.output(self.source.replace("🇺🇸 美国节点", "🇺🇸 美国地区"))

    def test_duplicate_group_stops_build(self):
        with self.assertRaises(build.BuildError):
            self.output(self.source + "custom_proxy_group=🇺🇸 美国节点`select`.*\n")

    def test_new_upstream_personal_group_requires_review(self):
        with self.assertRaises(build.BuildError):
            self.output(self.source + "custom_proxy_group=💳 PayPal`select`.*\n")

    def test_new_upstream_paypal_rule_requires_review(self):
        with self.assertRaises(build.BuildError):
            self.output(self.source + "ruleset=🎯 全球直连,[]GEOSITE,paypal\n")

    def test_missing_choice_stops_build(self):
        settings = copy.deepcopy(self.settings)
        settings["paypal"]["choices"].append("不存在的组")
        with self.assertRaises(build.BuildError):
            self.output(settings=settings)

    def test_changed_upstream_priority_stops_build(self):
        with self.assertRaises(build.BuildError):
            self.output(self.source.replace(build.ANCHORS[0],
                                            "ruleset=🎯 全球直连,[]GEOSITE,cn\n" + build.ANCHORS[0]))

    def test_cycle_stops_build(self):
        settings = copy.deepcopy(self.settings)
        settings["paypal"]["choices"].append(settings["paypal"]["name"])
        with self.assertRaises(build.BuildError):
            self.output(settings=settings)

    def test_unknown_group_type_stops_build(self):
        source = self.source.replace("custom_proxy_group=🇺🇸 美国节点`url-test`",
                                     "custom_proxy_group=🇺🇸 美国节点`smart`")
        with self.assertRaises(build.BuildError):
            self.output(source)

    def test_already_select_upstream_is_supported(self):
        line = next(x for x in self.source.splitlines()
                    if x.startswith("custom_proxy_group=🇺🇸 美国节点`"))
        fields = line[len(build.GROUP):].split("`")
        replacement = build.GROUP + "`".join([fields[0], "select", *fields[2:-2]])
        self.assertIn(replacement, self.output(self.source.replace(line, replacement)))

    def test_failure_preserves_previous_published_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build.run(self.source, "a" * 40, ROOT / "custom/settings.json", root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with self.assertRaises(build.BuildError):
                build.run(self.source.replace("🇺🇸 美国节点", "新美国组"), "b" * 40,
                          ROOT / "custom/settings.json", root)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_repeat_build_has_no_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build.run(self.source, "a" * 40, ROOT / "custom/settings.json", root)
            before = {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
            build.run(self.source, "a" * 40, ROOT / "custom/settings.json", root)
            after = {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
