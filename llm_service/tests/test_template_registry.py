import pytest

pytestmark = pytest.mark.asyncio


async def test_create_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="summarize",
        template_version="v1",
        knowledge_domain="cloud_core_network",
        purpose="Summarize document",
        user_prompt_template="Summarize: {{content}}",
        expected_output_type="json_object",
    )
    assert tpl_id is not None

    cur = await db.execute(
        "SELECT template_key, knowledge_domain, status FROM agent_llm_prompt_templates WHERE id = ?",
        (tpl_id,),
    )
    row = await cur.fetchone()
    assert row["template_key"] == "summarize"
    assert row["knowledge_domain"] == "cloud_core_network"
    assert row["status"] == "active"


async def test_get_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="extract",
        template_version="v1",
        knowledge_domain="generic",
        purpose="Extract entities",
        user_prompt_template="Extract: {{text}}",
        expected_output_type="json_array",
    )
    tpl = await reg.get(tpl_id)
    assert tpl["template_key"] == "extract"
    assert tpl["knowledge_domain"] == "generic"


async def test_get_by_key(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(
        template_key="qa",
        template_version="v1",
        purpose="Q&A",
        user_prompt_template="Answer: {{question}}",
        expected_output_type="text",
    )
    tpl = await reg.get_by_key("qa", "cloud_core_network")
    assert tpl is not None
    assert tpl["template_key"] == "qa"
    assert tpl["knowledge_domain"] is None


async def test_get_by_key_prefers_domain_specific_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(
        template_key="qa",
        template_version="v1",
        purpose="Global Q&A",
        user_prompt_template="Global answer: {{question}}",
        expected_output_type="text",
    )
    await reg.create(
        template_key="qa",
        template_version="v1-cn",
        knowledge_domain="cloud_core_network",
        purpose="Cloud core Q&A",
        user_prompt_template="Cloud answer: {{question}}",
        expected_output_type="text",
    )

    tpl = await reg.get_by_key("qa", "cloud_core_network")
    assert tpl is not None
    assert tpl["purpose"] == "Cloud core Q&A"
    assert tpl["knowledge_domain"] == "cloud_core_network"


async def test_list_templates(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(template_key="a", template_version="v1", purpose="A", user_prompt_template="A", expected_output_type="text")
    await reg.create(
        template_key="b",
        template_version="v1",
        knowledge_domain="cloud_core_network",
        purpose="B",
        user_prompt_template="B",
        expected_output_type="text",
    )
    templates = await reg.list_all("cloud_core_network")
    assert len(templates) == 2
    assert {tpl["template_key"] for tpl in templates} == {"a", "b"}


async def test_list_templates_filters_to_requested_domain(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(
        template_key="generic-only",
        template_version="v1",
        knowledge_domain="generic",
        purpose="Generic",
        user_prompt_template="G",
        expected_output_type="text",
    )
    await reg.create(
        template_key="cloud-only",
        template_version="v1",
        knowledge_domain="cloud_core_network",
        purpose="Cloud",
        user_prompt_template="C",
        expected_output_type="text",
    )

    templates = await reg.list_all("cloud_core_network")
    assert [tpl["template_key"] for tpl in templates] == ["cloud-only"]


async def test_update_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="update_me",
        template_version="v1",
        knowledge_domain="generic",
        purpose="Old purpose",
        user_prompt_template="Old template",
        expected_output_type="text",
    )
    await reg.update(tpl_id, purpose="New purpose", knowledge_domain="cloud_core_network")
    tpl = await reg.get(tpl_id)
    assert tpl["purpose"] == "New purpose"
    assert tpl["knowledge_domain"] == "cloud_core_network"


async def test_archive_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="to_archive",
        template_version="v1",
        knowledge_domain="generic",
        purpose="Will be archived",
        user_prompt_template="X",
        expected_output_type="text",
    )
    await reg.archive(tpl_id)
    tpl = await reg.get(tpl_id)
    assert tpl["status"] == "archived"
