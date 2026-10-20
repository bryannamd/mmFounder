import json
import os
import re
import unittest

from _load import ROOT, SKILLS_DIR

SKILLS = ["founder-rcf", "founder-board", "founder-marketing", "founder-cfo", "founder-consumer", "founder-launch",
          "founder-pricing", "founder-offer", "founder-competitors", "founder-brand", "founder-ops", "founder-plan"]
KR_SKILLS = ["founder-competitors", "founder-consumer", "founder-pricing", "founder-offer", "founder-cfo",
             "founder-marketing", "founder-brand", "founder-ops", "founder-launch"]
PIPELINE = ("rcf -> board -> competitors -> consumer -> pricing -> offer -> cfo -> marketing -> brand -> ops "
            "-> launch -> plan")
NAME = "mmfounder"
BANNED_KO = ("실측", "배선")


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


EM = chr(0x2014)  # built in code so this file does not trip its own check


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".txt", ".yaml", ".yml")) or f in ("LICENSE", ".gitignore"):
                yield os.path.join(base, f)


def read_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return json.load(fh)


class Repo(unittest.TestCase):
    def test_twelve_skill_folders(self):
        found = sorted(d for d in os.listdir(SKILLS_DIR) if os.path.isfile(os.path.join(SKILLS_DIR, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 300, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_tools_named_in_skills_exist(self):
        for s in SKILLS:
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            for tool in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([\w.\-/]+\.(?:py|md))", text):
                self.assertTrue(os.path.exists(os.path.normpath(os.path.join(SKILLS_DIR, s, tool))), "%s: %s" % (s, tool))

    def test_korean_notes_exist_and_are_linked(self):
        for s in KR_SKILLS:
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            self.assertIn("## In Korea", text, s)
            self.assertIn("${CLAUDE_SKILL_DIR}/kr.md", text, s)
            self.assertTrue(os.path.isfile(os.path.join(SKILLS_DIR, s, "kr.md")), s)
        self.assertTrue(os.path.isfile(os.path.join(SKILLS_DIR, "founder-rcf", "sources-kr.md")))
        _, rcf = frontmatter(os.path.join(SKILLS_DIR, "founder-rcf", "SKILL.md"))
        self.assertIn("${CLAUDE_SKILL_DIR}/sources-kr.md", rcf)

    def test_pipeline_line_starts_with_rcf(self):
        for s in ("founder-board", "founder-rcf"):
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            self.assertIn(PIPELINE, text, s)
        for s in SKILLS:
            _, text = frontmatter(os.path.join(SKILLS_DIR, s, "SKILL.md"))
            for line in text.splitlines():
                if line.startswith("board -> competitors"):
                    self.fail("%s still has the old pipeline line" % s)

    def test_board_has_the_outside_view_lens(self):
        with open(os.path.join(SKILLS_DIR, "founder-board", "lenses.md"), encoding="utf-8") as fh:
            self.assertIn("## The Outside View lens", fh.read())

    def test_codex_agent_files(self):
        for s in SKILLS:
            path = os.path.join(SKILLS_DIR, s, "agents", "openai.yaml")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertTrue(text.startswith("interface:\n"), s)
            for key in ("display_name:", "short_description:", "default_prompt:"):
                self.assertIn(key, text, s)
            self.assertIn("$%s:%s" % (NAME, s), text, s)

    def test_plugin_manifests(self):
        plugin = read_json(".claude-plugin", "plugin.json")
        self.assertEqual(plugin["name"], NAME)
        self.assertEqual(plugin["license"], "MIT")
        self.assertTrue(plugin["description"])
        market = read_json(".claude-plugin", "marketplace.json")
        self.assertEqual(market["name"], NAME)
        self.assertEqual(market["plugins"][0]["name"], NAME)
        self.assertEqual(market["plugins"][0]["source"], "./")
        codex = read_json("plugin.json")
        self.assertEqual(codex["name"], NAME)
        self.assertEqual(codex["license"], "MIT")
        self.assertIn("com.openai", codex["extensions"])
        agents = read_json(".agents", "plugins", "marketplace.json")
        self.assertEqual(agents["name"], NAME)
        self.assertEqual(agents["plugins"][0]["name"], NAME)
        self.assertEqual(agents["plugins"][0]["source"]["path"], "./")

    def test_readme_and_notices(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# mmFounder"))
        for line in (
            "사업을 열기 전에 시험하는 스킬 12개.",
            "Jakeschincariol/founder-skill",
            "fd9385b",
            "claude plugin marketplace add bryannamd/mmFounder",
            "claude plugin install mmfounder@mmfounder",
            "codex plugin add mmfounder@mmfounder",
            PIPELINE,
            "## 한계와 알아둘 점",
        ):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("`skills/%s`" % s, readme)
        with open(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), encoding="utf-8") as fh:
            notices = fh.read()
        for part in ("fd9385b", "Copyright (c) 2026 Jake Schincariol", "MIT License"):
            self.assertIn(part, notices)
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            lic = fh.read()
        self.assertIn("Copyright (c) 2026 Jake Schincariol", lic)
        self.assertIn("Copyright (c) 2026 bryannamd", lic)

    def test_examples_parse(self):
        for rel in ("founder-cfo/example.json", "founder-cfo/example.kr.json",
                    "founder-consumer/customer.example.json", "founder-consumer/customer.kr.example.json",
                    "founder-rcf/rcf.example.json"):
            with open(os.path.join(SKILLS_DIR, rel), encoding="utf-8") as fh:
                json.load(fh)

    def test_no_em_dashes(self):
        for path in text_files():
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn(EM, fh.read(), os.path.relpath(path, ROOT))

    def test_korean_docs_avoid_banned_words(self):
        for path in text_files():
            if not path.endswith(".md") or path.endswith("DESIGN.md"):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for word in BANNED_KO:
                self.assertNotIn(word, text, "%s: %s" % (os.path.relpath(path, ROOT), word))


if __name__ == "__main__":
    unittest.main()
