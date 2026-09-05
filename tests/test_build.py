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
        self.assertEqual(pay[-2:], [".*", "[]🏠 家宽节点"])
        rules = [x for x in output.splitlines() if x.startswith("ruleset=")]
        index = rules.index("ruleset=💳 PayPal,[]GEOSITE,paypal")
        self.assertEqual(rules[index - 1:index + 2], [
            "ruleset=🌎 国外媒体,[]GEOSITE,category-entertainment",
            "ruleset=💳 PayPal,[]GEOSITE,paypal",
            "ruleset=🛒 国外电商,[]GEOSITE,category-ecommerce",
        ])
        names = list(groups)
        for before, name, after in [("Ⓜ️ 微软服务", "💳 PayPal", "🎮 游戏平台"),
                                    ("🇰🇷 韩国节点", "🏠 家宽节点", "🎯 全球直连")]:
            index = names.index(name)
            self.assertEqual(names[index - 1:index + 2], [before, name, after])

    def placement_pairs(self):
        lines = self.source.splitlines()
        return [
            ["ruleset=🌎 国外媒体,[]GEOSITE,category-entertainment",
             "ruleset=🛒 国外电商,[]GEOSITE,category-ecommerce"],
            [next(x for x in lines if x.startswith(build.GROUP + name + "`"))
             for name in ["Ⓜ️ 微软服务", "🎮 游戏平台"]],
            [next(x for x in lines if x.startswith(build.GROUP + name + "`"))
             for name in ["🇰🇷 韩国节点", "🎯 全球直连"]],
        ]

    def test_missing_placement_anchors_stop_build(self):
        for pair in self.placement_pairs():
            for line in pair:
                with self.subTest(anchor=line), self.assertRaises(build.BuildError):
                    self.output(self.source.replace(line + "\n", ""))

    def test_reversed_placement_anchors_stop_build(self):
        for before, after in self.placement_pairs():
            with self.subTest(anchor=before), self.assertRaises(build.BuildError):
                self.output(self.source.replace(before + "\n" + after, after + "\n" + before))

    def test_new_entry_between_placement_anchors_requires_review(self):
        for before, after in self.placement_pairs():
            addition = ("ruleset=🎯 全球直连,[]GEOSITE,example" if before.startswith(build.RULE)
                        else "custom_proxy_group=新分组`select`[]DIRECT")
            with self.subTest(anchor=before), self.assertRaises(build.BuildError):
                self.output(self.source.replace(before + "\n" + after,
                                                before + "\n" + addition + "\n" + after))

    def test_comments_between_placement_anchors_survive(self):
        for before, after in self.placement_pairs():
            with self.subTest(anchor=before):
                output = self.output(self.source.replace(before + "\n" + after,
                                                         before + "\n; placement comment\n\n" + after))
                following = after.split("`")[0] if after.startswith(build.GROUP) else after
                self.assertIn("; placement comment\n\n" + following, output)

    def test_upstream_regex_improvements_survive(self):
        changed = self.source.replace("波特兰|", "新增美国城市|波特兰|", 1)
        fields = build.group_index(self.output(changed).splitlines())["🇺🇸 美国节点"][1]
        self.assertEqual(fields[1], "select")
        self.assertIn("新增美国城市|波特兰|", fields[2])

    def test_upstream_new_rule_and_group_survive(self):
        addition = "ruleset=新服务,[]GEOSITE,example\ncustom_proxy_group=新服务`select`[]🚀 手动选择\n"
        source = self.source.replace(";设置节点分组标志位", addition + ";设置节点分组标志位")
        output = self.output(source)
        self.assertIn(addition.splitlines()[0], output.splitlines())
        self.assertIn(addition.splitlines()[1] + "`[]🏠 家宽节点", output.splitlines())
        self.assertLess(output.index(addition.splitlines()[0]), output.index(addition.splitlines()[1]))

    def test_residential_is_last_choice_in_all_eligible_groups(self):
        groups = build.group_index(self.output().splitlines())
        excluded = {"🎯 全球直连", "🔀 非标端口", "🏠 家宽节点",
                    "🇭🇰 香港节点", "🇺🇸 美国节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点",
                    "🇼🇸 台湾节点", "🇰🇷 韩国节点"}
        for name, (_, fields) in groups.items():
            with self.subTest(group=name):
                if name in excluded:
                    self.assertNotIn("[]🏠 家宽节点", fields)
                else:
                    choices = fields[2:-2] if fields[1] == "url-test" else fields[2:]
                    self.assertEqual(choices[-1], "[]🏠 家宽节点")
                    self.assertEqual(choices.count("[]🏠 家宽节点"), 1)

    def test_excluded_groups_and_rules_are_unchanged(self):
        before = build.group_index(self.source.splitlines())
        after = build.group_index(self.output().splitlines())
        for name in ["🎯 全球直连", "🔀 非标端口"]:
            self.assertEqual(before[name][1], after[name][1])
        for name in self.settings["select_groups"]:
            fields = before[name][1]
            self.assertEqual(after[name][1], [name, "select", *fields[2:-2]])
        expected_rules = [x for x in self.source.splitlines() if x.startswith(build.RULE)]
        actual_rules = [x for x in self.output().splitlines() if x.startswith(build.RULE)
                        and x != "ruleset=💳 PayPal,[]GEOSITE,paypal"]
        self.assertEqual(actual_rules, expected_rules)

    def test_existing_residential_choices_are_moved_and_deduplicated(self):
        source = self.source.replace("custom_proxy_group=🚀 手动选择`select`",
                                     "custom_proxy_group=🚀 手动选择`select`[]🏠 家宽节点`[]🏠 家宽节点`")
        groups = build.group_index(self.output(source).splitlines())
        for name in ["🚀 手动选择", "💳 PayPal"]:
            self.assertEqual(groups[name][1].count("[]🏠 家宽节点"), 1)
            self.assertEqual(groups[name][1][-1], "[]🏠 家宽节点")

    def test_health_check_groups_keep_type_and_parameters(self):
        for kind in ["url-test", "fallback", "load-balance"]:
            with self.subTest(kind=kind):
                source = self.source.replace("custom_proxy_group=♻️ 自动选择`url-test`",
                                             "custom_proxy_group=♻️ 自动选择`" + kind + "`")
                fields = build.group_index(self.output(source).splitlines())["♻️ 自动选择"][1]
                self.assertEqual(fields, ["♻️ 自动选择", kind, ".*", "[]🏠 家宽节点",
                                          "https://cp.cloudflare.com/generate_204", "300,,50"])

    def test_invalid_health_check_layout_stops_build(self):
        line = next(x for x in self.source.splitlines() if x.startswith("custom_proxy_group=♻️ 自动选择`"))
        for malformed in [line.rsplit("`", 1)[0], line.replace("300,,50", "invalid"),
                          line.replace("`url-test`", "`unknown`")]:
            with self.subTest(line=malformed), self.assertRaises(build.BuildError):
                self.output(self.source.replace(line, malformed))

    def test_new_country_group_is_excluded(self):
        addition = "custom_proxy_group=🇩🇪 德国节点`url-test`德国`https://example.com/test`300\n"
        output = self.output(self.source + addition)
        self.assertIn(addition.strip(), output.splitlines())

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
