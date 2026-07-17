"""Repo-consistency checks: manifests parse, commands ↔ README table match,
one version string, no bare script paths, agent frontmatter constraints."""
import glob
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(path):
    return open(os.path.join(ROOT, path), encoding="utf-8").read()


def test_manifests_parse_and_agree():
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    assert plugin["name"] == "intensive-research"
    entry = market["plugins"][0]
    assert entry["version"] == plugin["version"]
    for skill_path in entry["skills"]:
        assert os.path.isfile(os.path.join(ROOT, skill_path, "SKILL.md")), skill_path


def test_single_version_string():
    version = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))["version"]
    readme = _read("README.md")
    assert version in readme  # README states the version once...
    for md in glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True):
        assert version not in open(md, encoding="utf-8").read(), f"version leaked into {md}"


def test_commands_match_readme_table():
    readme = _read("README.md")
    commands = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(ROOT, "commands", "*.md"))}
    for cmd in commands:
        assert f"/{cmd}" in readme, f"/{cmd} missing from README command table"
    for cmd in re.findall(r"`/(ir-[a-z-]+)", readme):
        assert cmd in commands, f"README references /{cmd} which has no command file"


def test_no_bare_script_paths():
    """Every scholar.py invocation in prompt content must be CLAUDE_PLUGIN_ROOT-qualified."""
    offenders = []
    for pattern in ("agents/*.md", "commands/*.md", "skills/**/*.md"):
        for f in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            for i, line in enumerate(open(f, encoding="utf-8"), 1):
                if re.search(r"python3 scripts/", line):
                    offenders.append(f"{f}:{i}")
    assert not offenders, offenders


def test_agent_frontmatter_constraints():
    for f in glob.glob(os.path.join(ROOT, "agents", "*.md")):
        txt = open(f, encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---", txt, re.S)
        assert m, f
        fm = m.group(1)
        assert re.search(r"^name:", fm, re.M) and re.search(r"^description:", fm, re.M)
        assert re.search(r"^tools:", fm, re.M) and re.search(r"^model:", fm, re.M)
        for forbidden in ("permissionMode", "mcpServers", "hooks:"):
            assert forbidden not in fm, f"{f} carries plugin-ignored key {forbidden}"
        tools = re.search(r"^tools:\s*(.+)$", fm, re.M).group(1)
        assert "Task" not in tools and "Agent(" not in tools, f"{f} must not spawn subagents"


def test_intensity_table_single_source_of_truth():
    canonical = "skills/intensive-research/references/intensity-levels.md"
    assert os.path.isfile(os.path.join(ROOT, canonical))
    # No other file re-defines the searcher row of the table.
    for md in glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True):
        if md.endswith("intensity-levels.md"):
            continue
        txt = open(md, encoding="utf-8").read()
        assert "Parallel searchers (wave 1)" not in txt, f"intensity table duplicated in {md}"


def test_fanout_protocol_wording_present():
    flagship = _read("skills/intensive-research/phases/1-discovery.md")
    assert "ONE message" in flagship and "parallel Task" in flagship
    review = _read("skills/peer-review/SKILL.md")
    assert "ONE message" in review


def test_claim_audit_gold_fixture_valid():
    gold = json.load(open(os.path.join(ROOT, "tests", "fixtures", "claim_audit_gold.json")))
    assert len(gold["tuples"]) >= 15
    verdicts = {"VERIFIED", "MINOR_DISTORTION", "MAJOR_DISTORTION",
                "UNVERIFIABLE", "UNVERIFIABLE_ACCESS"}
    for t in gold["tuples"]:
        assert t["expected_verdict"] in verdicts, t
        assert t["claim"] and t["source_passage"] is not None


# ---- v2 consistency ----

def test_checklists_parse_and_pinned():
    base = os.path.join(ROOT, "skills", "intensive-research", "references", "checklists")
    files = glob.glob(os.path.join(base, "*.json"))
    assert len(files) >= 6
    for f in files:
        data = json.load(open(f, encoding="utf-8"))
        assert data.get("items"), f
        for it in data["items"]:
            for key in ("id", "section", "requirement_text", "canonical_source_url",
                        "severity", "auto_detectable"):
                assert key in it, (f, it.get("id"), key)
            assert it["severity"] in ("must", "should")
            assert it["auto_detectable"] in ("regex", "structural", "llm-judge")
            url = it["canonical_source_url"]
            # Pin stable PMC/journal/DOI/publisher URLs, never EQUATOR slugs (they 404).
            assert "equator-network.org" not in url, (f, it["id"])
            assert url.startswith("http"), (f, it["id"])
            if it["auto_detectable"] == "regex":
                assert it.get("pattern"), (f, it["id"])
            if it["auto_detectable"] == "structural":
                assert it.get("check"), (f, it["id"])


def test_no_llm_judge_mustpass_without_reviewer():
    base = os.path.join(ROOT, "skills", "intensive-research", "references", "checklists")
    for f in glob.glob(os.path.join(base, "*.json")):
        for it in json.load(open(f, encoding="utf-8"))["items"]:
            if it["auto_detectable"] == "llm-judge" and it["severity"] == "must":
                assert it.get("reviewer"), (f, it["id"])  # must declare who adjudicates


def test_dataset_registries_agree():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "scholar_apis", os.path.join(ROOT, "scripts", "scholar_apis.py"))
    mod = importlib.util.module_from_spec(spec)
    import sys as _s
    _s.path.insert(0, os.path.join(ROOT, "scripts"))
    spec.loader.exec_module(mod)
    assert set(mod.DATASET_ADAPTERS.keys()) == set(mod.DATASET_SOURCES)
    assert set(mod.DEFAULT_DATASET_SOURCES) <= set(mod.DATASET_SOURCES)


def test_new_fanout_phases_wording():
    for rel in ("skills/experiment-design/SKILL.md",
                "skills/paper-writing/phases/2.5-figures.md",
                "skills/intensive-research/phases/7-figures.md"):
        txt = _read(rel)
        assert "ONE message" in txt, rel


def test_experiment_design_skill_present():
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    skills = market["plugins"][0]["skills"]
    assert "./skills/experiment-design" in skills
    assert os.path.isfile(os.path.join(ROOT, "skills", "experiment-design", "SKILL.md"))


def test_v2_agents_present_and_legal():
    for a in ("ir-style-analyst", "ir-dataset-scout", "ir-figure-designer", "ir-figure-critic"):
        assert os.path.isfile(os.path.join(ROOT, "agents", f"{a}.md"))
    # figure-critic must have Write but not Bash (persist critique, cannot execute).
    critic = _read("agents/ir-figure-critic.md")
    tools = re.search(r"^tools:\s*(.+)$", critic, re.M).group(1)
    assert "Write" in tools and "Bash" not in tools


def test_all_skill_descriptions_under_limit():
    for f in glob.glob(os.path.join(ROOT, "skills", "**", "SKILL.md"), recursive=True):
        txt = open(f, encoding="utf-8").read()
        m = re.search(r"^description:\s*(.*)$", txt, re.M)
        assert m, f
        assert len(m.group(1)) <= 1024, (f, len(m.group(1)))
