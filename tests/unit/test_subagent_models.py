from storycraftr.subagents.models import SubAgentRole


def test_sub_agent_role_to_dict():
    role = SubAgentRole(
        slug="researcher",
        name="Researcher",
        description="A specialized researcher for background information.",
        command_whitelist=["!search", "!web-read"],
        system_prompt="You are a researcher. Use the tools to find information.",
        language="en",
        persona="Formal and methodical",
        temperature=0.3,
    )

    expected_dict = {
        "slug": "researcher",
        "name": "Researcher",
        "description": "A specialized researcher for background information.",
        "command_whitelist": ["!search", "!web-read"],
        "system_prompt": "You are a researcher. Use the tools to find information.",
        "language": "en",
        "persona": "Formal and methodical",
        "temperature": 0.3,
    }

    assert role.to_dict() == expected_dict


def test_sub_agent_role_from_dict():
    slug = "editor"
    data = {
        "name": "Head Editor",
        "description": "Edits the manuscript for clarity and flow.",
        "command_whitelist": ["!refine", "!outline"],
        "system_prompt": "You are a head editor. Be critical but constructive.",
        "language": "es",
        "persona": "Experienced and wise",
        "temperature": 0.5,
    }

    role = SubAgentRole.from_dict(slug, data)

    assert role.slug == "editor"
    assert role.name == "Head Editor"
    assert role.description == "Edits the manuscript for clarity and flow."
    assert role.command_whitelist == ["!refine", "!outline"]
    assert role.system_prompt == "You are a head editor. Be critical but constructive."
    assert role.language == "es"
    assert role.persona == "Experienced and wise"
    assert role.temperature == 0.5


def test_sub_agent_role_roundtrip():
    original_role = SubAgentRole(
        slug="critic",
        name="Reviewer",
        description="Provides feedback on story beats.",
        command_whitelist=["!review"],
        system_prompt="Review the content.",
        language="fr",
        persona="Harsh and cynical",
        temperature=0.7,
    )

    role_dict = original_role.to_dict()
    new_role = SubAgentRole.from_dict(original_role.slug, role_dict)

    assert original_role == new_role
    assert new_role.to_dict() == role_dict


def test_sub_agent_role_from_dict_defaults():
    slug = "default-agent"
    data = {}

    role = SubAgentRole.from_dict(slug, data)

    assert role.slug == "default-agent"
    assert role.name == "Default-Agent"  # title case from slug
    assert role.description == ""
    assert role.command_whitelist == []
    assert role.system_prompt == ""
    assert role.language == "en"
    assert role.persona == ""
    assert role.temperature == 0.2


def test_sub_agent_role_from_dict_missing_fields():
    """Test that missing fields in the dictionary use appropriate defaults."""
    slug = "test-slug"
    data = {}

    role = SubAgentRole.from_dict(slug, data)

    assert role.slug == "test-slug"
    assert role.name == "Test-Slug"
    assert role.description == ""
    assert role.command_whitelist == []
    assert role.system_prompt == ""
    assert role.language == "en"
    assert role.persona == ""
    assert role.temperature == 0.2
